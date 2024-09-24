import json
import sys


def decode_bencode(bencoded_value):
    if chr(bencoded_value[0]).isdigit():
        first_colon_index = bencoded_value.find(b":")
        if first_colon_index == -1:
            raise ValueError("Invalid bencoded string: missing colon")
        length = int(bencoded_value[:first_colon_index])
        start_index = first_colon_index + 1
        end_index = start_index + length
        if end_index > len(bencoded_value):
            raise ValueError("Invalid bencoded string: length mismatch")
        return bencoded_value[start_index:end_index]
    elif bencoded_value[0] == ord("i"):
        end_index = bencoded_value.find(b"e", 1)
        if end_index == -1:
            raise ValueError("Invalid encoded integer: missing 'e'")
        try:
            return int(bencoded_value[1:end_index])
        except ValueError:
            raise ValueError("Invalid encoded integer: non-numeric content")
    else:
        raise NotImplementedError("Unsupported bencode type")


def main():
    command = sys.argv[1]
    if command == "decode":
        bencoded_value = sys.argv[2].encode()

        def bytes_to_str(data):
            if isinstance(data, bytes):
                return data.decode()
            raise TypeError(f"Type not serializable: {type(data)}")

        decoded_value = decode_bencode(bencoded_value)
        print(json.dumps(decoded_value, default=bytes_to_str))
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
