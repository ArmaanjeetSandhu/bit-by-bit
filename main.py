import json
import sys


def decode_bencode(bencoded_value):
    if isinstance(bencoded_value, int):
        return bencoded_value, b""
    if chr(bencoded_value[0]).isdigit():
        first_colon_index = bencoded_value.find(b":")
        if first_colon_index == -1:
            raise ValueError("Invalid bencoded string: missing colon")
        length = int(bencoded_value[:first_colon_index])
        start_index = first_colon_index + 1
        end_index = start_index + length
        if end_index > len(bencoded_value):
            raise ValueError("Invalid bencoded string: length mismatch")
        return bencoded_value[start_index:end_index], bencoded_value[end_index:]
    elif bencoded_value[0] == ord("i"):
        end_index = bencoded_value.find(b"e", 1)
        if end_index == -1:
            raise ValueError("Invalid encoded integer: missing 'e'")
        try:
            return int(bencoded_value[1:end_index]), bencoded_value[end_index + 1 :]
        except ValueError:
            raise ValueError("Invalid encoded integer: non-numeric content")
    elif bencoded_value[0] == ord("l"):
        decoded_list = []
        rest = bencoded_value[1:]
        while rest and rest[0] != ord("e"):
            decoded_item, rest = decode_bencode(rest)
            decoded_list.append(decoded_item)
        if not rest or rest[0] != ord("e"):
            raise ValueError("Invalid bencoded list: missing 'e'")
        return decoded_list, rest[1:]
    elif bencoded_value[0] == ord("d"):
        decoded_dict = {}
        rest = bencoded_value[1:]
        while rest and rest[0] != ord("e"):
            key, rest = decode_bencode(rest)
            if not isinstance(key, bytes):
                raise ValueError("Invalid bencoded dictionary: key must be a string")
            value, rest = decode_bencode(rest)
            decoded_dict[key] = value
        if not rest or rest[0] != ord("e"):
            raise ValueError("Invalid bencoded dictionary: missing 'e'")
        return decoded_dict, rest[1:]
    else:
        raise ValueError(f"Unsupported bencode type: {chr(bencoded_value[0])}")


def bytes_to_str(data):
    if isinstance(data, bytes):
        return data.decode()
    if isinstance(data, dict):
        return {bytes_to_str(k): bytes_to_str(v) for k, v in data.items()}
    if isinstance(data, list):
        return [bytes_to_str(item) for item in data]
    return data


def main():
    command = sys.argv[1]
    if command == "decode":
        bencoded_value = sys.argv[2].encode()
        decoded_value, _ = decode_bencode(bencoded_value)
        decoded_value = bytes_to_str(decoded_value)
        print(json.dumps(decoded_value))
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
