import struct
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class EveMessage:
    index: int
    start_word: int
    end_word: int
    file_offset: int
    words: tuple[int, ...]

    @property
    def size_bytes(self) -> int:
        return (self.end_word - self.start_word) * 2


@dataclass(frozen=True)
class EvePage:
    index: int
    content_start_word: int
    content_end_word: int
    boundary_codes: tuple[int, ...]
    words: tuple[int, ...]


@dataclass(frozen=True)
class EveBank:
    table_offset: int
    body_offset: int
    pointers: tuple[int, ...]
    messages: tuple[EveMessage, ...]

    @classmethod
    def parse(
        cls,
        data: bytes,
        table_offset: int,
        body_offset: int,
    ) -> "EveBank":
        if not 0 <= table_offset < body_offset <= len(data):
            raise ValueError("EVE table/body offsets are outside the source file")

        pointers = []
        cursor = table_offset
        while cursor + 2 <= body_offset:
            pointer = struct.unpack_from(">H", data, cursor)[0]
            cursor += 2
            if pointer == 0xFFFF:
                break
            pointers.append(pointer)
        else:
            raise ValueError("EVE pointer table has no 0xffff terminator")

        # Every entry before 0xffff is a message start.  There is no synthetic
        # end pointer; the final message's terminator is its end boundary.
        if not pointers:
            raise ValueError("EVE pointer table has no message pointers")
        if pointers[0] != 0:
            raise ValueError(f"EVE first pointer is {pointers[0]:#x}, expected zero")
        if any(left >= right for left, right in zip(pointers, pointers[1:])):
            raise ValueError("EVE pointers are not strictly increasing")

        final_start = body_offset + pointers[-1] * 2
        if final_start + 2 > len(data):
            raise ValueError("EVE message body exceeds the source file")

        final_end = None
        for offset in range(final_start, len(data) - 1, 2):
            if struct.unpack_from(">H", data, offset)[0] == 0x8000:
                final_end = offset + 2
                break
        if final_end is None:
            raise ValueError("EVE final message has no 0x8000 terminator")
        if any(data[final_end:]):
            raise ValueError("EVE final message is not followed by zero padding")

        final_end_word = (final_end - body_offset) // 2
        end_words = (*pointers[1:], final_end_word)

        messages = []
        for index, (start_word, end_word) in enumerate(zip(pointers, end_words)):
            start = body_offset + start_word * 2
            words = struct.unpack_from(f">{end_word - start_word}H", data, start)
            messages.append(
                EveMessage(
                    index=index,
                    start_word=start_word,
                    end_word=end_word,
                    file_offset=start,
                    words=words,
                )
            )

        return cls(
            table_offset=table_offset,
            body_offset=body_offset,
            pointers=tuple(pointers),
            messages=tuple(messages),
        )

    @property
    def body_size_bytes(self) -> int:
        return self.messages[-1].end_word * 2

    def body_bytes(self) -> bytes:
        return b"".join(
            struct.pack(f">{len(message.words)}H", *message.words)
            for message in self.messages
        )

    def rebuild(
        self,
        source_data: bytes,
        message_words: Sequence[Sequence[int]],
    ) -> bytes:
        if len(message_words) != len(self.messages):
            raise ValueError(
                f"EVE rebuild has {len(message_words)} messages; "
                f"expected {len(self.messages)}"
            )

        pointers = []
        body = bytearray()
        for message_index, words in enumerate(message_words):
            words = tuple(words)
            if not words:
                raise ValueError(f"EVE message {message_index} is empty")
            if any(not 0 <= word <= 0xFFFF for word in words):
                raise ValueError(f"EVE message {message_index} has a non-u16 word")
            pointer = len(body) // 2
            if pointer > 0xFFFF:
                raise ValueError("EVE message pointers exceed 16-bit word offsets")
            pointers.append(pointer)
            body.extend(struct.pack(f">{len(words)}H", *words))

        if message_words[-1][-1] != 0x8000:
            raise ValueError("EVE final message must end with 0x8000")
        table_size = (len(pointers) + 1) * 2
        if table_size > self.body_offset - self.table_offset:
            raise ValueError("EVE pointer table exceeds the table region")
        capacity = len(source_data) - self.body_offset
        if len(body) > capacity:
            raise ValueError(f"EVE body overflow: {len(body)} > {capacity} bytes")

        # Keep the table gap and unused body capacity byte-identical.  Only a
        # body contraction needs explicit clearing of the old message tail.
        output = bytearray(source_data)
        for index, pointer in enumerate(pointers):
            struct.pack_into(">H", output, self.table_offset + index * 2, pointer)
        struct.pack_into(
            ">H",
            output,
            self.table_offset + len(pointers) * 2,
            0xFFFF,
        )
        output[self.body_offset : self.body_offset + len(body)] = body
        if len(body) < self.body_size_bytes:
            old_body_end = self.body_offset + self.body_size_bytes
            output[self.body_offset + len(body) : old_body_end] = b"\x00" * (
                self.body_size_bytes - len(body)
            )
        return bytes(output)
