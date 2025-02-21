from typing import Union, Tuple, List, Dict, Any

BencodeType = Union[str, int, List[Any], Dict[str, Any]]


def decode_bencode(bdata: str) -> BencodeType:
    """
    Decode a bencoded string.

    Args:
        bdata (str): The bencoded string to decode

    Returns:
        The decoded value (str, int, list, or dict)

    Example:
        >>> decode_bencode("4:spam")
        'spam'
        >>> decode_bencode("i42e")
        42
        >>> decode_bencode("l4:spami42ee")
        ['spam', 42]
        >>> decode_bencode("d3:foo3:bar5:helloi52ee")
        {'foo': 'bar', 'hello': 52}
    """

    def decode_next(data: str, pos: int) -> Tuple[BencodeType, int]:
        if not data:
            raise ValueError("Empty bencode data")

        char = data[pos]

        # String
        if char.isdigit():
            colon = data.find(":", pos)
            if colon == -1:
                raise ValueError("Invalid string format")
            length = int(data[pos:colon])
            string_start = colon + 1
            string_end = string_start + length
            return data[string_start:string_end], string_end

        # Integer
        elif char == "i":
            end = data.find("e", pos)
            if end == -1:
                raise ValueError("Invalid integer format")
            return int(data[pos + 1 : end]), end + 1

        # List
        elif char == "l":
            pos += 1
            items: List[BencodeType] = []
            while pos < len(data) and data[pos] != "e":
                item, pos = decode_next(data, pos)
                items.append(item)
            return items, pos + 1

        # Dictionary
        elif char == "d":
            pos += 1
            dictionary: Dict[str, BencodeType] = {}
            while pos < len(data) and data[pos] != "e":
                key, pos = decode_next(data, pos)
                if not isinstance(key, str):
                    raise ValueError("Dictionary key must be string")
                value, pos = decode_next(data, pos)
                dictionary[key] = value
            return dictionary, pos + 1

        else:
            raise ValueError(f"Invalid initial byte: {char}")

    decoded, _ = decode_next(bdata, 0)
    return decoded
