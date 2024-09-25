import json
import sys
from typing import Union, Tuple, List, Dict, Any

class BencodeDecodeError(Exception):
    """Custom exception for Bencode decoding errors."""
    pass

def decode_bencode(bencoded_value: bytes) -> Tuple[Union[int, bytes, List, Dict], bytes]:
    """
    Decode a Bencoded value.

    Args:
        bencoded_value (bytes): The Bencoded value to decode.

    Returns:
        Tuple[Union[int, bytes, List, Dict], bytes]: A tuple containing the decoded value and any remaining bytes.

    Raises:
        BencodeDecodeError: If the input is invalid or unsupported.
    """
    if not bencoded_value:
        raise BencodeDecodeError("Empty input")

    if isinstance(bencoded_value, int):
        return bencoded_value, b""

    if chr(bencoded_value[0]).isdigit():
        return _decode_string(bencoded_value)
    elif bencoded_value[0] == ord("i"):
        return _decode_integer(bencoded_value)
    elif bencoded_value[0] == ord("l"):
        return _decode_list(bencoded_value)
    elif bencoded_value[0] == ord("d"):
        return _decode_dict(bencoded_value)
    else:
        raise BencodeDecodeError(f"Unsupported Bencode type: {chr(bencoded_value[0])}")

def _decode_string(bencoded_value: bytes) -> Tuple[bytes, bytes]:
    """Decode a Bencoded string."""
    first_colon_index = bencoded_value.find(b":")
    if first_colon_index == -1:
        raise BencodeDecodeError("Invalid Bencoded string: missing colon")
    try:
        length = int(bencoded_value[:first_colon_index])
    except ValueError:
        raise BencodeDecodeError("Invalid Bencoded string: non-numeric length")
    start_index = first_colon_index + 1
    end_index = start_index + length
    if end_index > len(bencoded_value):
        raise BencodeDecodeError("Invalid Bencoded string: length mismatch")
    return bencoded_value[start_index:end_index], bencoded_value[end_index:]

def _decode_integer(bencoded_value: bytes) -> Tuple[int, bytes]:
    """Decode a Bencoded integer."""
    end_index = bencoded_value.find(b"e", 1)
    if end_index == -1:
        raise BencodeDecodeError("Invalid encoded integer: missing 'e'")
    try:
        return int(bencoded_value[1:end_index]), bencoded_value[end_index + 1:]
    except ValueError:
        raise BencodeDecodeError("Invalid encoded integer: non-numeric content")

def _decode_list(bencoded_value: bytes) -> Tuple[List, bytes]:
    """Decode a Bencoded list."""
    decoded_list = []
    rest = bencoded_value[1:]
    while rest and rest[0] != ord("e"):
        decoded_item, rest = decode_bencode(rest)
        decoded_list.append(decoded_item)
    if not rest or rest[0] != ord("e"):
        raise BencodeDecodeError("Invalid Bencoded list: missing 'e'")
    return decoded_list, rest[1:]

def _decode_dict(bencoded_value: bytes) -> Tuple[Dict, bytes]:
    """Decode a Bencoded dictionary."""
    decoded_dict = {}
    rest = bencoded_value[1:]
    while rest and rest[0] != ord("e"):
        key, rest = decode_bencode(rest)
        if not isinstance(key, bytes):
            raise BencodeDecodeError("Invalid Bencoded dictionary: key must be a string")
        value, rest = decode_bencode(rest)
        decoded_dict[key] = value
    if not rest or rest[0] != ord("e"):
        raise BencodeDecodeError("Invalid Bencoded dictionary: missing 'e'")
    return decoded_dict, rest[1:]

def decode_bytes_in_structure(data: Any) -> Any:
    """
    Recursively decode bytes to strings in a data structure.

    Args:
        data (Any): The data structure to process.

    Returns:
        Any: The processed data structure with bytes decoded to strings.
    """
    if isinstance(data, bytes):
        return data.decode()
    if isinstance(data, dict):
        return {decode_bytes_in_structure(k): decode_bytes_in_structure(v) for k, v in data.items()}
    if isinstance(data, list):
        return [decode_bytes_in_structure(item) for item in data]
    return data

def main():
    """Main function to handle command-line interface."""
    try:
        if len(sys.argv) < 3:
            raise ValueError("Insufficient arguments. Usage: python script.py <command> <bencoded_value>")

        command = sys.argv[1]
        if command == "decode":
            bencoded_value = sys.argv[2].encode()
            decoded_value, _ = decode_bencode(bencoded_value)
            decoded_value = decode_bytes_in_structure(decoded_value)
            print(json.dumps(decoded_value))
        else:
            raise NotImplementedError(f"Unknown command {command}")
    except (BencodeDecodeError, ValueError, NotImplementedError) as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()