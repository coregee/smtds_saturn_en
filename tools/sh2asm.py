"""
sh2asm — tiny two-pass SH-2 assembler for Saturn patch caves.

Replaces hand-written u16 word lists with text mnemonics for larger patches.
Big-endian SH-2 output; capstone is used only by the self-test as an independent
verifier.

    from sh2asm import assemble
    blob = assemble(source, base_addr, symbols={"g_state": 0x06045e8c})
    blob            # bytes (subclass) — the assembled blob
    blob.warnings   # list[str] — delay-slot hazards etc. (never fatal)
    blob.labels     # {label: absolute address}
    blob.items      # [(kind, off, size, lineno, info)] layout map (code/lit/pad/data)

Syntax
  - one instruction per line; ';' comments; labels `name:` alone or before an
    instruction; mnemonics/registers case-insensitive, symbols case-sensitive.
  - expressions: symbols, labels, hex 0x.., binary 0b.., decimal, + - * ( ) and
    unary minus. Label value = base_addr + offset.
  - `mov.l =EXPR, rN` / `mov.w =EXPR, rN`: load the VALUE of EXPR via a
    deduplicated literal pool (dedup key = normalized expression text, per
    pool). The pool is emitted at the next `.pool` directive, else at the end
    of the blob (.l slots first, 4-aligned; then .w slots). Raises if the
    @(disp,PC) displacement exceeds 255 words — add a `.pool` closer.
  - `mov.l ADDR, rN` (bare expression) = PC-relative load FROM that address
    (must be in range/aligned); this is also what capstone prints. `@(d,pc)`
    with a byte displacement is accepted too.
  - `mova =LABEL, r0` / `mova LABEL, r0`: r0 = address of LABEL (4-aligned,
    0..1020 bytes past PC&~3). No pool slot is allocated.
  - directives: `.pool`, `.align 2|4|8|16`, `.byte e,..`, `.word e,..`,
    `.long e,..` (must be 4-aligned — raise otherwise), `.ascii "..."` (with
    \\n \\r \\t \\0 \\\\ \\" \\xNN escapes). Alignment pads are zero bytes: keep
    pools/data behind an unconditional branch, as caves already do.
  - branches take a label or absolute-address expression; displacement uses the
    PC+4 rule; range overflow raises.

Warnings (blob.warnings, non-fatal): a branch in the delay slot of
bra/bsr/jsr/jmp/rts/braf/bsrf/rte/bt.s/bf.s (slot-illegal on SH-2), and a
delay slot that falls on data/padding or off the end of the blob.

Encodings follow the Renesas SH-1/SH-2 programming manual; the self-test
round-trips every emitted instruction through capstone 5 (CS_ARCH_SH,
CS_MODE_SH2|CS_MODE_BIG_ENDIAN) and spot-checks known words from the manual.
Run:  py sh2asm.py                      (self-test)
      py sh2asm.py file.s 0x06065c60 g_state=0x06045e8c   (assemble to hex)
"""

import re
import struct
from collections import namedtuple

__all__ = ["AsmBlob", "AsmError", "assemble"]


class AsmError(Exception):
    """Assembly failure: syntax, range, alignment, unknown symbol/mnemonic."""


class AsmBlob(bytes):
    def __new__(cls, data, base, warnings, labels, items):
        self = super().__new__(cls, data)
        self.base = base
        self.warnings = warnings
        self.labels = labels
        self.items = items
        return self


Item = namedtuple("Item", "kind off size lineno info")

# ---------------------------------------------------------------- expressions
_NUM_RE = re.compile(r"0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+")
_ID_RE = re.compile(r"[A-Za-z_.][A-Za-z0-9_.]*")


def _eval_expr(text, env, where):
    toks, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit():
            m = _NUM_RE.match(text, i)
            s = m.group(0)
            base = 16 if s[:2].lower() == "0x" else 2 if s[:2].lower() == "0b" else 10
            toks.append(int(s, base))
            i = m.end()
            continue
        m = _ID_RE.match(text, i)
        if m:
            name = m.group(0)
            if name not in env:
                raise AsmError(f"{where}: undefined symbol '{name}' in '{text}'")
            toks.append(env[name])
            i = m.end()
            continue
        if c in "+-*()":
            toks.append(c)
            i += 1
            continue
        raise AsmError(f"{where}: bad character {c!r} in expression '{text}'")
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        v = toks[pos[0]]
        pos[0] += 1
        return v

    def atom():
        t = peek()
        if t == "(":
            take()
            v = addsub()
            if peek() != ")":
                raise AsmError(f"{where}: missing ')' in '{text}'")
            take()
            return v
        if t == "-":
            take()
            return -atom()
        if t == "+":
            take()
            return atom()
        if isinstance(t, int):
            return take()
        raise AsmError(f"{where}: malformed expression '{text}'")

    def mul():
        v = atom()
        while peek() == "*":
            take()
            v *= atom()
        return v

    def addsub():
        v = mul()
        while peek() in ("+", "-"):
            v = v + mul() if take() == "+" else v - mul()
        return v

    if not toks:
        raise AsmError(f"{where}: empty expression")
    v = addsub()
    if pos[0] != len(toks):
        raise AsmError(f"{where}: trailing junk in expression '{text}'")
    return v


# ------------------------------------------------------------------- parsing
_LABEL_RE = re.compile(r"^([A-Za-z_.][A-Za-z0-9_.]*)\s*:\s*(.*)$")
_REG_RE = re.compile(r"[rR]([0-9]|1[0-5])")


def _strip_comment(line):
    inq = esc = False
    for i, c in enumerate(line):
        if inq:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                inq = False
        elif c == '"':
            inq = True
        elif c == ";":
            return line[:i]
    return line


def _regnum(s):
    s = s.strip()
    m = _REG_RE.fullmatch(s)
    if m:
        return int(m.group(1))
    if s.lower() == "sp":
        return 15
    return None


def _split_commas(s):
    parts, depth, start = [], 0, 0
    for i, c in enumerate(s):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return [p.strip() for p in parts]


def _operand(s, where):
    t = s.strip()
    if not t:
        raise AsmError(f"{where}: empty operand")
    if t.startswith("#"):
        return ("imm", t[1:].strip())
    if t.startswith("="):
        return ("pool", t[1:].strip())
    low = t.lower()
    if low in ("pr", "macl", "mach"):
        return (low,)
    r = _regnum(t)
    if r is not None:
        return ("reg", r)
    if t.startswith("@"):
        u = t[1:].strip()
        if u.startswith("-"):
            r = _regnum(u[1:])
            if r is None:
                raise AsmError(f"{where}: bad pre-decrement operand '{s}'")
            return ("predec", r)
        if u.endswith("+"):
            r = _regnum(u[:-1])
            if r is None:
                raise AsmError(f"{where}: bad post-increment operand '{s}'")
            return ("postinc", r)
        if u.startswith("("):
            if not u.endswith(")"):
                raise AsmError(f"{where}: unbalanced parens in operand '{s}'")
            parts = _split_commas(u[1:-1])
            if len(parts) != 2:
                raise AsmError(f"{where}: bad @(...) operand '{s}'")
            a, b = parts
            if b.lower() == "pc":
                return ("pcdisp", a)
            rb = _regnum(b)
            if rb is None:
                raise AsmError(f"{where}: bad base register in '{s}'")
            ra = _regnum(a)
            if ra == 0:
                return ("r0ind", rb)
            if ra is not None:
                raise AsmError(
                    f"{where}: only r0 is a valid index in @(rM,rN) on SH-2: '{s}'"
                )
            return ("dispind", a, rb)
        r = _regnum(u)
        if r is not None:
            return ("ind", r)
        raise AsmError(f"{where}: bad memory operand '{s}'")
    return ("expr", t)


def _ascii_bytes(arg, where):
    s = arg.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        raise AsmError(f"{where}: .ascii needs a double-quoted string")
    body, out, i = s[1:-1], bytearray(), 0
    esc = {"n": 10, "r": 13, "t": 9, "0": 0, "\\": 92, '"': 34}
    while i < len(body):
        c = body[i]
        if c == "\\":
            e = body[i + 1 : i + 2]
            if e == "x":
                try:
                    out.append(int(body[i + 2 : i + 4], 16))
                except ValueError:
                    raise AsmError(f"{where}: bad \\x escape in .ascii")
                i += 4
                continue
            if e not in esc:
                raise AsmError(f"{where}: unknown escape '\\{e}' in .ascii")
            out.append(esc[e])
            i += 2
            continue
        if ord(c) > 255:
            raise AsmError(f"{where}: non-Latin-1 char {c!r} in .ascii")
        out.append(ord(c))
        i += 1
    return bytes(out)


# ---------------------------------------------------------- encoding tables
_SZ = {"b": 0, "w": 1, "l": 2}
_ZERO_OP = {
    "rts": 0x000B,
    "nop": 0x0009,
    "rte": 0x002B,
    "clrt": 0x0008,
    "sett": 0x0018,
    "clrmac": 0x0028,
    "div0u": 0x0019,
    "sleep": 0x001B,
}
_ONE_R4 = {
    "dt": 0x10,
    "cmp/pz": 0x11,
    "cmp/pl": 0x15,
    "shll": 0x00,
    "shlr": 0x01,
    "shll2": 0x08,
    "shlr2": 0x09,
    "shll8": 0x18,
    "shlr8": 0x19,
    "shll16": 0x28,
    "shlr16": 0x29,
    "shal": 0x20,
    "shar": 0x21,
    "rotl": 0x04,
    "rotr": 0x05,
    "rotcl": 0x24,
    "rotcr": 0x25,
}
_ONE_R0 = {"movt": 0x29, "braf": 0x23, "bsrf": 0x03}
_TWO_R = {
    "add": (0x3, 0xC),
    "addc": (0x3, 0xE),
    "sub": (0x3, 0x8),
    "subc": (0x3, 0xA),
    "neg": (0x6, 0xB),
    "negc": (0x6, 0xA),
    "not": (0x6, 0x7),
    "and": (0x2, 0x9),
    "or": (0x2, 0xB),
    "xor": (0x2, 0xA),
    "tst": (0x2, 0x8),
    "cmp/eq": (0x3, 0x0),
    "cmp/hs": (0x3, 0x2),
    "cmp/ge": (0x3, 0x3),
    "cmp/hi": (0x3, 0x6),
    "cmp/gt": (0x3, 0x7),
    "extu.b": (0x6, 0xC),
    "extu.w": (0x6, 0xD),
    "exts.b": (0x6, 0xE),
    "exts.w": (0x6, 0xF),
    "swap.b": (0x6, 0x8),
    "swap.w": (0x6, 0x9),
    "mulu.w": (0x2, 0xE),
    "muls.w": (0x2, 0xF),
    "dmulu.l": (0x3, 0x5),
    "dmuls.l": (0x3, 0xD),
    "mul.l": (0x0, 0x7),
}
_IMM_R0 = {"and": 0xC9, "or": 0xCB, "xor": 0xCA, "tst": 0xC8, "cmp/eq": 0x88}
_STS = {"mach": 0x0A, "macl": 0x1A, "pr": 0x2A}  # sts SRC,Rn   (0x0n__)
_STSL = {"mach": 0x02, "macl": 0x12, "pr": 0x22}  # sts.l SRC,@-Rn (0x4n__)
_LDS = {"mach": 0x0A, "macl": 0x1A, "pr": 0x2A}  # lds Rm,DST   (0x4m__)
_LDSL = {"mach": 0x06, "macl": 0x16, "pr": 0x26}  # lds.l @Rm+,DST (0x4m__)
_B8 = {"bt": 0x8900, "bf": 0x8B00, "bt.s": 0x8D00, "bf.s": 0x8F00}
_DELAY = {"bra", "bsr", "jsr", "jmp", "rts", "braf", "bsrf", "rte", "bt.s", "bf.s"}
_BRANCHY = _DELAY | {"bt", "bf"}
_KNOWN = (
    set(_ZERO_OP)
    | set(_ONE_R4)
    | set(_ONE_R0)
    | set(_TWO_R)
    | set(_B8)
    | {
        "mov",
        "mov.b",
        "mov.w",
        "mov.l",
        "mova",
        "add",
        "jsr",
        "jmp",
        "bra",
        "bsr",
        "sts",
        "sts.l",
        "lds",
        "lds.l",
    }
)


def _imm8(e, env, where):
    v = _eval_expr(e, env, where)
    if not -128 <= v <= 255:
        raise AsmError(f"{where}: immediate {v} out of range -128..255")
    return v & 0xFF


def _disp(v, scale, maxq, where, what):
    if v % scale:
        raise AsmError(f"{where}: {what} displacement {v} not a multiple of {scale}")
    q = v // scale
    if not 0 <= q <= maxq:
        raise AsmError(
            f"{where}: {what} displacement {v} out of range 0..{maxq * scale}"
        )
    return q


def _encode(mnem, ops, addr, env, ctx):
    poolseq, lit_off, base, where, text = ctx
    kinds = tuple(op[0] for op in ops)

    def bad():
        raise AsmError(f"{where}: bad operands for '{mnem}': '{text}'")

    def pcrel(target, size):  # size: 1=.w  2=.l/mova
        if size == 2:
            pc, scale = (addr + 4) & ~3, 4
        else:
            pc, scale = addr + 4, 2
        delta = target - pc
        if delta < 0 or delta % scale or delta // scale > 255:
            raise AsmError(
                f"{where}: PC-relative target {target:#x} out of range "
                f"({delta:+#x} from PC {pc:#x}) — use '=' pool syntax?"
            )
        return delta // scale

    if mnem in _ZERO_OP:
        if ops:
            bad()
        return _ZERO_OP[mnem]

    if mnem in ("mov", "mov.b", "mov.w", "mov.l"):
        if len(ops) != 2:
            bad()
        a, b = ops
        sz = None if mnem == "mov" else _SZ[mnem[-1]]
        if a[0] == "imm" and b[0] == "reg":
            if sz is not None:
                raise AsmError(
                    f"{where}: '{mnem} #imm,rN' does not exist — use plain 'mov'"
                )
            return 0xE000 | b[1] << 8 | _imm8(a[1], env, where)
        if a[0] == "reg" and b[0] == "reg":
            if sz is not None:
                raise AsmError(
                    f"{where}: '{mnem} rM,rN' does not exist — use plain 'mov'"
                )
            return 0x6003 | b[1] << 8 | a[1] << 4
        if sz is None:
            raise AsmError(
                f"{where}: memory/pool mov needs a size suffix (.b/.w/.l): '{text}'"
            )
        if a[0] == "pool" and b[0] == "reg":
            if sz == 0:
                raise AsmError(
                    f"{where}: no mov.b @(disp,PC) form on SH-2 — use mov.w/mov.l"
                )
            key = (poolseq, "l" if sz == 2 else "w", re.sub(r"\s+", "", a[1]))
            loff = lit_off.get(key)
            if loff is None:
                raise AsmError(f"{where}: internal: unresolved pool literal '{a[1]}'")
            lit_addr = base + loff
            if sz == 2:
                pc, scale = (addr + 4) & ~3, 4
            else:
                pc, scale = addr + 4, 2
            delta = lit_addr - pc
            if delta < 0:
                raise AsmError(
                    f"{where}: literal slot at {lit_addr:#x} is before PC "
                    f"{pc:#x} — the pool must sit at least one instruction "
                    f"past the load (after the rts/nop is typical)"
                )
            disp = delta // scale
            if disp > 255:
                raise AsmError(
                    f"{where}: literal pool too far ({disp} words, max 255) — "
                    f"add a .pool closer to this instruction"
                )
            return (0xD000 if sz == 2 else 0x9000) | b[1] << 8 | disp
        if a[0] in ("expr", "pcdisp") and b[0] == "reg":
            if sz == 0:
                raise AsmError(f"{where}: no mov.b @(disp,PC) form on SH-2")
            if a[0] == "expr":
                disp = pcrel(_eval_expr(a[1], env, where), sz)
            else:
                d = _eval_expr(a[1], env, where)
                disp = _disp(d, 4 if sz == 2 else 2, 255, where, "@(d,PC)")
            return (0xD000 if sz == 2 else 0x9000) | b[1] << 8 | disp
        if a[0] == "ind" and b[0] == "reg":
            return 0x6000 | b[1] << 8 | a[1] << 4 | sz
        if a[0] == "reg" and b[0] == "ind":
            return 0x2000 | b[1] << 8 | a[1] << 4 | sz
        if a[0] == "postinc" and b[0] == "reg":
            return 0x6004 | b[1] << 8 | a[1] << 4 | sz
        if a[0] == "reg" and b[0] == "predec":
            return 0x2004 | b[1] << 8 | a[1] << 4 | sz
        if a[0] == "r0ind" and b[0] == "reg":
            return (0x000C | sz) | b[1] << 8 | a[1] << 4
        if a[0] == "reg" and b[0] == "r0ind":
            return (0x0004 | sz) | b[1] << 8 | a[1] << 4
        if a[0] == "dispind" and b[0] == "reg":
            d = _eval_expr(a[1], env, where)
            if sz == 2:
                return 0x5000 | b[1] << 8 | a[2] << 4 | _disp(d, 4, 15, where, "mov.l")
            if b[1] != 0:
                raise AsmError(
                    f"{where}: mov.{'bw'[sz]} @(disp,rM),Rn requires Rn=r0 on SH-2"
                )
            return (0x8400 | sz << 8) | a[2] << 4 | _disp(d, sz + 1, 15, where, mnem)
        if a[0] == "reg" and b[0] == "dispind":
            d = _eval_expr(b[1], env, where)
            if sz == 2:
                return 0x1000 | b[2] << 8 | a[1] << 4 | _disp(d, 4, 15, where, "mov.l")
            if a[1] != 0:
                raise AsmError(
                    f"{where}: mov.{'bw'[sz]} Rm,@(disp,rN) requires Rm=r0 on SH-2"
                )
            return (0x8000 | sz << 8) | b[2] << 4 | _disp(d, sz + 1, 15, where, mnem)
        bad()

    if mnem == "mova":
        if len(ops) != 2 or ops[1] != ("reg", 0):
            raise AsmError(f"{where}: mova destination must be r0: '{text}'")
        a = ops[0]
        if a[0] in ("expr", "pool"):
            disp = pcrel(_eval_expr(a[1], env, where), 2)
        elif a[0] == "pcdisp":
            disp = _disp(_eval_expr(a[1], env, where), 4, 255, where, "mova")
        else:
            bad()
        return 0xC700 | disp

    if mnem == "add" and kinds and kinds[0] == "imm":
        if len(ops) != 2 or ops[1][0] != "reg":
            bad()
        return 0x7000 | ops[1][1] << 8 | _imm8(ops[0][1], env, where)
    if mnem in _IMM_R0 and kinds and kinds[0] == "imm":
        if len(ops) != 2 or ops[1] != ("reg", 0):
            raise AsmError(
                f"{where}: '{mnem} #imm' pairs only with r0 on SH-2: '{text}'"
            )
        return _IMM_R0[mnem] << 8 | _imm8(ops[0][1], env, where)
    if mnem in _TWO_R:
        if kinds != ("reg", "reg"):
            bad()
        top, low = _TWO_R[mnem]
        return top << 12 | ops[1][1] << 8 | ops[0][1] << 4 | low
    if mnem in _ONE_R4:
        if kinds != ("reg",):
            bad()
        return 0x4000 | ops[0][1] << 8 | _ONE_R4[mnem]
    if mnem in _ONE_R0:
        if kinds != ("reg",):
            bad()
        return ops[0][1] << 8 | _ONE_R0[mnem]
    if mnem in ("jsr", "jmp"):
        if kinds != ("ind",):
            raise AsmError(f"{where}: {mnem} takes @rN: '{text}'")
        return 0x4000 | ops[0][1] << 8 | (0x0B if mnem == "jsr" else 0x2B)

    if mnem in ("bra", "bsr") or mnem in _B8:
        if kinds != ("expr",):
            bad()
        target = _eval_expr(ops[0][1], env, where)
        delta = target - (addr + 4)
        if delta % 2:
            raise AsmError(f"{where}: branch target {target:#x} is odd")
        disp = delta // 2
        if mnem in ("bra", "bsr"):
            if not -2048 <= disp <= 2047:
                raise AsmError(
                    f"{where}: {mnem} target out of range (disp {disp} words, max ±2047)"
                )
            return (0xA000 if mnem == "bra" else 0xB000) | (disp & 0xFFF)
        if not -128 <= disp <= 127:
            raise AsmError(
                f"{where}: {mnem} target out of range (disp {disp} words, max ±127)"
            )
        return _B8[mnem] | (disp & 0xFF)

    if mnem == "sts" and len(ops) == 2 and kinds[0] in _STS and ops[1][0] == "reg":
        return ops[1][1] << 8 | _STS[kinds[0]]
    if (
        mnem == "sts.l"
        and len(ops) == 2
        and kinds[0] in _STSL
        and ops[1][0] == "predec"
    ):
        return 0x4000 | ops[1][1] << 8 | _STSL[kinds[0]]
    if mnem == "lds" and len(ops) == 2 and ops[0][0] == "reg" and kinds[1] in _LDS:
        return 0x4000 | ops[0][1] << 8 | _LDS[kinds[1]]
    if (
        mnem == "lds.l"
        and len(ops) == 2
        and ops[0][0] == "postinc"
        and kinds[1] in _LDSL
    ):
        return 0x4000 | ops[0][1] << 8 | _LDSL[kinds[1]]

    if mnem in _KNOWN:
        bad()
    raise AsmError(f"{where}: unknown mnemonic '{mnem}'")


# ------------------------------------------------------------------ assemble
def assemble(source, base_addr, symbols=None):
    """Assemble SH-2 `source` at `base_addr` -> AsmBlob (big-endian bytes +
    .warnings/.labels/.items). Raises AsmError on any syntax/range problem."""
    symbols = dict(symbols or {})
    items, labels = [], {}
    pend, pend_seen, pend_line = [], set(), {}
    lit_off = {}
    seq, off = 0, 0

    def flush_pool(lineno):
        nonlocal off, seq, pend, pend_seen
        if any(sz == "l" for sz, _ in pend):
            pad = (-off) % 4
            if pad:
                items.append(Item("pad", off, pad, lineno, None))
                off += pad
        elif pend and off % 2:
            items.append(Item("pad", off, 1, lineno, None))
            off += 1
        for sz, key in [p for p in pend if p[0] == "l"] + [
            p for p in pend if p[0] == "w"
        ]:
            size = 4 if sz == "l" else 2
            lit_off[(seq, sz, key)] = off
            items.append(Item("lit", off, size, pend_line[(sz, key)], (sz, key)))
            off += size
        seq += 1
        pend, pend_seen = [], set()

    for lineno, raw in enumerate(source.splitlines(), 1):
        line = _strip_comment(raw).strip()
        where = f"line {lineno}"
        while True:
            m = _LABEL_RE.match(line)
            if not m:
                break
            name = m.group(1)
            if _regnum(name) is not None or name.lower() in (
                "pc",
                "pr",
                "macl",
                "mach",
            ):
                raise AsmError(f"{where}: label '{name}' shadows a register name")
            if name in labels:
                raise AsmError(f"{where}: duplicate label '{name}'")
            if name in symbols:
                raise AsmError(f"{where}: label '{name}' collides with a symbol")
            labels[name] = off
            line = m.group(2).strip()
        if not line:
            continue
        if line.startswith("."):
            parts = line.split(None, 1)
            d, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
            if d == ".pool":
                flush_pool(lineno)
            elif d == ".align":
                try:
                    n = int(arg, 0)
                except ValueError:
                    raise AsmError(f"{where}: .align needs a numeric argument")
                if n not in (2, 4, 8, 16):
                    raise AsmError(f"{where}: .align {n} unsupported (2/4/8/16)")
                pad = (-off) % n
                if pad:
                    items.append(Item("pad", off, pad, lineno, None))
                    off += pad
            elif d in (".byte", ".word", ".long"):
                if not arg:
                    raise AsmError(f"{where}: {d} needs at least one expression")
                exprs = _split_commas(arg)
                unit = {".byte": 1, ".word": 2, ".long": 4}[d]
                if unit == 2 and off % 2:
                    raise AsmError(
                        f"{where}: misaligned .word at offset {off:#x} — add .align 2"
                    )
                if unit == 4 and off % 4:
                    raise AsmError(
                        f"{where}: misaligned .long at offset {off:#x} — add .align 4"
                    )
                items.append(Item(d[1:], off, unit * len(exprs), lineno, exprs))
                off += unit * len(exprs)
            elif d == ".ascii":
                data = _ascii_bytes(arg, where)
                items.append(Item("ascii", off, len(data), lineno, data))
                off += len(data)
            else:
                raise AsmError(f"{where}: unknown directive '{d}'")
            continue
        parts = line.split(None, 1)
        mnem = {"bt/s": "bt.s", "bf/s": "bf.s"}.get(parts[0].lower(), parts[0].lower())
        opstr = parts[1].strip() if len(parts) > 1 else ""
        ops = [_operand(o, where) for o in _split_commas(opstr)] if opstr else []
        if off % 2:
            raise AsmError(
                f"{where}: instruction at odd offset {off:#x} — add .align 2"
            )
        if mnem in ("mov.l", "mov.w"):
            for op in ops:
                if op[0] == "pool":
                    k = (mnem[-1], re.sub(r"\s+", "", op[1]))
                    if k not in pend_seen:
                        pend_seen.add(k)
                        pend.append(k)
                        pend_line[k] = lineno
        items.append(Item("code", off, 2, lineno, (mnem, ops, seq, line)))
        off += 2
    flush_pool(None)

    env = dict(symbols)
    for name, o in labels.items():
        env[name] = base_addr + o

    buf = bytearray()
    for it in items:
        assert len(buf) == it.off, "internal layout mismatch"
        where = f"line {it.lineno}" if it.lineno else "pool"
        if it.kind == "pad":
            buf += b"\x00" * it.size
        elif it.kind == "ascii":
            buf += it.info
        elif it.kind in ("byte", "word", "long"):
            lo, hi, fmt = {
                "byte": (-128, 0xFF, None),
                "word": (-32768, 0xFFFF, ">H"),
                "long": (-(1 << 31), 0xFFFFFFFF, ">I"),
            }[it.kind]
            for e in it.info:
                v = _eval_expr(e, env, where)
                if not lo <= v <= hi:
                    raise AsmError(f"{where}: .{it.kind} value {v} out of range")
                if fmt:
                    buf += struct.pack(fmt, v & hi)
                else:
                    buf.append(v & 0xFF)
        elif it.kind == "lit":
            sz, key = it.info
            v = _eval_expr(key, env, where)
            if sz == "l":
                if not -(1 << 31) <= v <= 0xFFFFFFFF:
                    raise AsmError(f"{where}: literal {v:#x} out of 32-bit range")
                buf += struct.pack(">I", v & 0xFFFFFFFF)
            else:
                if not -32768 <= v <= 0xFFFF:
                    raise AsmError(f"{where}: mov.w literal {v} out of 16-bit range")
                buf += struct.pack(">H", v & 0xFFFF)
        elif it.kind == "code":
            mnem, ops, poolseq, text = it.info
            ctx = (poolseq, lit_off, base_addr, where, text)
            buf += struct.pack(">H", _encode(mnem, ops, base_addr + it.off, env, ctx))

    warnings = []
    for idx, it in enumerate(items):
        if it.kind != "code" or it.info[0] not in _DELAY:
            continue
        mnem = it.info[0]
        nxt = items[idx + 1] if idx + 1 < len(items) else None
        if nxt is None:
            warnings.append(
                f"line {it.lineno}: '{mnem}' delay slot runs off the end of the blob — add a nop"
            )
        elif nxt.kind != "code":
            warnings.append(
                f"line {it.lineno}: '{mnem}' delay slot lands on {nxt.kind} (not code) — add a nop"
            )
        elif nxt.info[0] in _BRANCHY:
            warnings.append(
                f"line {nxt.lineno}: branch '{nxt.info[0]}' in the delay slot of "
                f"'{mnem}' (line {it.lineno}) — slot-illegal on SH-2"
            )
    return AsmBlob(
        bytes(buf),
        base_addr,
        warnings,
        {k: base_addr + v for k, v in labels.items()},
        items,
    )


# ------------------------------------------------------------------ self-test
_TEST_SRC = """
; comprehensive coverage: every supported form
start:
    mov     #0x10, r3
    mov     #-0x10, r4
    mov     r5, r6
    mov.l   =g_state, r1        ; pool literal (.l)
    mov.l   =g_state, r2        ; deduped -> same slot
    mov.l   =g_state + 4*2, r3  ; expression literal
    mov.l   =start, r4          ; label literal
    mov.w   =0x1234, r5         ; pool literal (.w)
    mov.w   =-2, r6
    mov.l   @r1, r2
    mov.w   @r1, r2
    mov.b   @r1, r2
    mov.l   r2, @r1
    mov.w   r2, @r1
    mov.b   r2, @r1
    mov.l   @r1+, r2
    mov.w   @r1+, r2
    mov.b   @r1+, r2
    mov.l   r2, @-r1
    mov.w   r2, @-r1
    mov.b   r2, @-r1
    mov.l   @(4, r1), r2
    mov.l   @(k_small - 60, r1), r2
    mov.l   r2, @(4, r1)
    mov.w   @(2, r2), r0
    mov.w   r0, @(2, r2)
    mov.b   @(3, r2), r0
    mov.b   r0, @(3, r2)
    mov.l   @(r0, r1), r2
    mov.w   @(r0, r1), r2
    mov.b   @(r0, r1), r0
    mov.l   r2, @(r0, r1)
    mov.w   r2, @(r0, r1)
    mov.b   r2, @(r0, r1)
    add     #8, r1
    add     #-8, r1
    add     r2, r3
    sub     r2, r3
    neg     r2, r3
    negc    r2, r3
    addc    r2, r3
    subc    r2, r3
    not     r2, r3
    cmp/eq  #4, r0
    cmp/eq  r2, r3
    cmp/hs  r3, r0
    cmp/hi  r2, r3
    cmp/ge  r2, r3
    cmp/gt  r2, r3
    cmp/pz  r3
    cmp/pl  r3
    tst     r2, r3
    tst     #0x80, r0
    and     r2, r3
    and     #0x0f, r0
    or      r2, r3
    or      #0x0f, r0
    xor     r2, r3
    xor     #0x0f, r0
    extu.b  r0, r3
    extu.w  r0, r3
    exts.b  r0, r3
    exts.w  r0, r3
    swap.b  r2, r3
    swap.w  r2, r3
    shll    r4
    shlr    r4
    shll2   r8
    shlr2   r8
    shll8   r4
    shlr8   r4
    shll16  r4
    shlr16  r4
    shal    r4
    shar    r4
    rotl    r4
    rotr    r4
    rotcl   r4
    rotcr   r4
    mulu.w  r2, r3
    muls.w  r2, r3
    dmulu.l r2, r3
    dmuls.l r2, r3
    mul.l   r2, r3
    sts     macl, r2
    sts     mach, r2
    sts     pr, r2
    sts.l   pr, @-r15
    sts.l   macl, @-r15
    lds.l   @r15+, pr
    lds.l   @r15+, macl
    lds     r3, pr
    lds     r3, macl
    dt      r7
    movt    r5
back:
    nop
    bra     fwd
    nop
    bsr     back
    nop
fwd:
    bt      back
    bf      fwd2
    bt.s    back
    nop
    bf.s    fwd2
    nop
fwd2: jsr   @r1
    nop
    braf    r2
    nop
    bsrf    r3
    nop
    jmp     @r4
    nop
    rts
    nop
    .pool                       ; flush pool #0 here
after_pool:
    mov.l   =0x12345678, r7
    mov.l   =g_state, r0        ; pool #1: its own slot
    mov.w   =k_small, r9
    mova    =msg, r0            ; '=' address form
    mova    msg, r0             ; bare form, same meaning
    rts
    nop
    .align  4
msg:
    .ascii  "Hi\\x00!"
    .byte   0xff, 1, -1
    .align  2
wexpr:
    .word   -(2+3)*4
    .word   0x1234, msg - start
    .align  4
lconst:
    .long   g_state + 4, -1
end_lbl:
"""

_TEST_BASE = 0x06065000
_TEST_SYMS = {"g_state": 0x06045E8C, "k_small": 0x40}


def _expect_err(src, frag, symbols=None):
    try:
        assemble(src, 0x06000000, symbols)
    except AsmError as e:
        assert frag.lower() in str(e).lower(), f"wrong error for {src!r}: {e}"
        return str(e)
    raise AssertionError(f"no AsmError raised for {src!r} (expected ~'{frag}')")


def _selftest():
    import capstone

    def enc1(line, addr=0x06000000, syms=None):
        return struct.unpack(">H", bytes(assemble(line, addr, syms))[:2])[0]

    # 1) known encodings from the Renesas SH-2 manual (+ house fetch_cave words)
    known = [
        ("mov #0x10,r3", 0xE310),
        ("mov.l @r1,r2", 0x6212),
        ("mov.l r2,@(4,r1)", 0x1121),
        ("rts", 0x000B),
        ("mov.w r0,@(2,r2)", 0x8121),
        ("mov.b @(r0,r1),r0", 0x001C),
        ("sts.l pr,@-r15", 0x4F22),
        ("jsr @r1", 0x410B),
        ("extu.b r0,r3", 0x630C),
        ("dt r7", 0x4710),
        ("shll2 r8", 0x4808),
        ("mov.l @r10,r1", 0x61A2),
        ("add #-8,r0", 0x70F8),
        ("mov #0x78,r3", 0xE378),
        ("cmp/hs r3,r0", 0x3032),
        ("jmp @r3", 0x432B),
        ("cmp/eq #-1,r0", 0x88FF),
        ("tst #128,r0", 0xC880),
        ("lds.l @r15+,pr", 0x4F26),
        ("sts pr,r2", 0x022A),
        ("lds r3,pr", 0x432A),
        ("bsrf r3", 0x0303),
        ("braf r0", 0x0023),
        ("nop", 0x0009),
        ("mov.w @r1+,r2", 0x6215),
        ("mov.l r1,@r10", 0x2A12),
        ("extu.w r2,r2", 0x622D),
        ("shlr8 r7", 0x4719),
        ("mov.l r5,@-r15", 0x2F56),
        ("mov.b r0,@(3,r2)", 0x8023),
        ("mov r7,r2", 0x6273),
        ("mov.l r1,@(4,r0)", 0x1011),
    ]
    for line, want in known:
        got = enc1(line)
        assert got == want, f"{line!r}: got {got:04X}, want {want:04X}"
    # bra disp calc: +0 (to PC+4), and backward
    assert enc1("bra t\nnop\nt:") == 0xA000
    assert enc1("t: bra t+4") == 0xA000
    b = assemble("t: nop\nbra t\nnop", 0x06000000)
    assert struct.unpack_from(">H", b, 2)[0] == 0xAFFD  # disp -3
    # pool disp mechanics: lit at +8 -> disp 1; .w lit at +6 -> disp 1
    b = assemble("mov.l =0x11223344,r1\nrts\nnop", 0x06000000)
    assert (
        struct.unpack_from(">H", b, 0)[0] == 0xD101 and b[8:12] == b"\x11\x22\x33\x44"
    ), b.hex()
    b = assemble("mov.w =0x1234,r5\nrts\nnop", 0x06000000)
    assert struct.unpack_from(">H", b, 0)[0] == 0x9501 and b[6:8] == b"\x12\x34", (
        b.hex()
    )

    # 2) comprehensive program: assemble, then round-trip through capstone
    blob = assemble(_TEST_SRC, _TEST_BASE, _TEST_SYMS)
    assert blob.warnings == [], blob.warnings
    assert blob.labels["start"] == _TEST_BASE
    md = capstone.Cs(
        capstone.CS_ARCH_SH, capstone.CS_MODE_SH2 | capstone.CS_MODE_BIG_ENDIAN
    )
    n_code = 0
    for it in blob.items:
        if it.kind != "code":
            continue
        n_code += 1
        addr = _TEST_BASE + it.off
        raw = blob[it.off : it.off + 2]
        dec = list(md.disasm(raw, addr))
        assert len(dec) == 1, (
            f"capstone rejects {raw.hex()} @{addr:#x} ({it.info[3]!r})"
        )
        ins = dec[0]
        csmnem = {"bt/s": "bt.s", "bf/s": "bf.s"}.get(ins.mnemonic, ins.mnemonic)
        assert csmnem == it.info[0], (
            f"mnemonic drift: mine={it.info[0]} capstone={ins.mnemonic}"
        )
        line = (ins.mnemonic + " " + ins.op_str).strip()
        again = bytes(assemble(line, addr))[:2]
        assert again == bytes(raw), (
            f"round-trip fail {it.info[3]!r}: {raw.hex()} -> '{line}' -> {again.hex()}"
        )
    assert n_code >= 100, n_code

    # 3) pool contents: dedup + values
    lits = [(it.off, it.info) for it in blob.items if it.kind == "lit"]
    assert len(lits) == 8, lits  # pool0: 3l+2w, pool1: 2l+1w

    def lit_val(key, sz="l"):
        for off, (s, k) in lits:
            if (s, k) == (sz, key):
                return struct.unpack_from(">I" if sz == "l" else ">H", blob, off)[0]
        raise AssertionError(f"no literal {key!r}")

    assert lit_val("g_state") == 0x06045E8C
    assert lit_val("g_state+4*2") == 0x06045E94
    assert lit_val("start") == _TEST_BASE
    assert lit_val("0x1234", "w") == 0x1234
    assert lit_val("-2", "w") == 0xFFFE
    assert lit_val("0x12345678") == 0x12345678
    assert lit_val("k_small", "w") == 0x40

    # 4) directives landed correctly
    moff = blob.labels["msg"] - _TEST_BASE
    assert moff % 4 == 0 and blob[moff : moff + 4] == b"Hi\x00!"
    assert blob[moff + 4 : moff + 7] == b"\xff\x01\xff"
    woff = blob.labels["wexpr"] - _TEST_BASE
    assert blob[woff : woff + 2] == b"\xff\xec"  # -(2+3)*4 = -20
    assert struct.unpack_from(">H", blob, woff + 4)[0] == moff  # msg - start
    loff = blob.labels["lconst"] - _TEST_BASE
    assert loff % 4 == 0
    assert struct.unpack_from(">I", blob, loff)[0] == 0x06045E90
    assert struct.unpack_from(">I", blob, loff + 4)[0] == 0xFFFFFFFF

    # 5) delay-slot warnings
    w = assemble("bra t\nbt t\nt: nop", 0x06000000).warnings
    assert any("delay slot" in s and "bt" in s for s in w), w
    w = assemble("rts\n.word 0", 0x06000000).warnings
    assert any("delay slot" in s for s in w), w
    w = assemble("rts", 0x06000000).warnings
    assert any("end of the blob" in s for s in w), w

    # 6) error paths
    _expect_err("bt far\n" + "nop\n" * 130 + "far: nop", "out of range")
    _expect_err("mov.l =5,r1\n" + ".word 0\n" * 520 + ".pool", "too far")
    _expect_err("frobnicate r1", "unknown mnemonic")
    _expect_err(".byte 1\n.long 0", "misaligned .long")
    _expect_err(".byte 1\n.word 0", "misaligned .word")
    _expect_err("mov.b @(4,r1),r5", "r0")
    _expect_err("mov.w r3,@(2,r1)", "r0")
    _expect_err("mov.l @(64,r1),r2", "out of range")
    _expect_err("mov.l @(3,r1),r2", "multiple")
    _expect_err("mov #0x1ff,r1", "out of range")
    _expect_err("mov.l =nosuch,r1", "undefined symbol")
    _expect_err("x: nop\nx: nop", "duplicate")
    _expect_err("mov.w =0x12345,r1\nrts\nnop", "16-bit")
    _expect_err("mov.w =1,r1", "before PC")  # .w pool right after its load
    _expect_err("and #15,r3", "r0")
    _expect_err("bra r1", "bad operands")
    _expect_err("mov.l #4,r1", "plain 'mov'")
    _expect_err("mova t,r0\nt: nop", "out of range")  # t is behind PC&~3

    return {
        "code_insns": n_code,
        "known_encodings": len(known) + 5,
        "pool_literals": len(lits),
        "error_paths": 18,
        "blob_bytes": len(blob),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            src = f.read()
        syms = {}
        for kv in sys.argv[3:]:
            k, v = kv.split("=", 1)
            syms[k] = int(v, 0)
        blob = assemble(src, int(sys.argv[2], 0), syms)
        for wmsg in blob.warnings:
            print("WARNING:", wmsg, file=sys.stderr)
        print(blob.hex())
    else:
        stats = _selftest()
        print("sh2asm self-test: ALL GREEN")
        for k, v in sorted(stats.items()):
            print(f"  {k}: {v}")
