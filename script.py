import json
import sys
import os
import argparse
import hashlib
from typing import Union, Tuple, List, Dict, Any

ENCODING = "utf-8"


class BencodeDecodeError(Exception):
    """Custom exception for Bencode decoding errors."""

    pass


def encode_bencode(data):
    if isinstance(data, int):
        return f"i{data}e".encode(ENCODING)
    elif isinstance(data, bytes):
        return f"{len(data)}:".encode(ENCODING) + data
    elif isinstance(data, str):
        return encode_bencode(data.encode(ENCODING))
    elif isinstance(data, list):
        return b"l" + b"".join(encode_bencode(item) for item in data) + b"e"
    elif isinstance(data, dict):
        encoded = b"d"
        for key, value in sorted(data.items()):
            encoded += encode_bencode(key) + encode_bencode(value)
        return encoded + b"e"
    else:
        raise ValueError(f"Cannot encode {type(data)} in Bencode")


def decode_bencode(
    bencoded_value: bytes,
) -> Tuple[Union[int, bytes, List, Dict], bytes]:
    """
    Decode a Bencode-encoded value.

    Args:
        bencoded_value (bytes): The Bencode-encoded value to decode.

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
    """Decode a Bencode-encoded string."""
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
    """Decode a Bencode-encoded integer."""
    end_index = bencoded_value.find(b"e", 1)
    if end_index == -1:
        raise BencodeDecodeError("Invalid encoded integer: missing 'e'")
    try:
        return int(bencoded_value[1:end_index]), bencoded_value[end_index + 1 :]
    except ValueError:
        raise BencodeDecodeError("Invalid encoded integer: non-numeric content")


def _decode_list(bencoded_value: bytes) -> Tuple[List, bytes]:
    """Decode a Bencode-encoded list."""
    decoded_list = []
    rest = bencoded_value[1:]
    while rest and rest[0] != ord("e"):
        decoded_item, rest = decode_bencode(rest)
        decoded_list.append(decoded_item)
    if not rest or rest[0] != ord("e"):
        raise BencodeDecodeError("Invalid Bencoded list: missing 'e'")
    return decoded_list, rest[1:]


def _decode_dict(bencoded_value: bytes) -> Tuple[Dict, bytes]:
    """Decode a Bencode-encoded dictionary."""
    decoded_dict = {}
    rest = bencoded_value[1:]
    while rest and rest[0] != ord("e"):
        key, rest = decode_bencode(rest)
        if not isinstance(key, bytes):
            raise BencodeDecodeError(
                "Invalid Bencoded dictionary: key must be a string"
            )
        value, rest = decode_bencode(rest)
        decoded_dict[key] = value
    if not rest or rest[0] != ord("e"):
        raise BencodeDecodeError("Invalid Bencoded dictionary: missing 'e'")
    return decoded_dict, rest[1:]


def decode_bytes_in_structure(data: Any) -> Union[str, Dict, List, Any]:
    """
    Recursively decode bytes to strings in a data structure.

    Args:
        data (Any): The data structure to process.

    Returns:
        Union[str, Dict, List, Any]: The processed data structure with bytes decoded to strings.
    """
    if isinstance(data, bytes):
        return data.decode(ENCODING)
    if isinstance(data, dict):
        return {
            decode_bytes_in_structure(k): decode_bytes_in_structure(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [decode_bytes_in_structure(item) for item in data]
    return data


def calculate_info_hash(info_dict):
    info_bencoded = encode_bencode(info_dict)
    return hashlib.sha1(info_bencoded).hexdigest()


def decode_command(bencoded_value: str) -> None:
    """Handle the 'decode' command."""
    try:
        decoded_value, _ = decode_bencode(bencoded_value.encode(ENCODING))
        decoded_value = decode_bytes_in_structure(decoded_value)
        print(json.dumps(decoded_value))
    except json.JSONDecodeError as e:
        print(
            f"Error: Unable to JSON encode the decoded value. {str(e)}", file=sys.stderr
        )
        sys.exit(1)


def info_command(file_name: str) -> None:
    """Handle the 'info' command."""
    if not os.path.exists(file_name):
        raise FileNotFoundError(f"The file {file_name} does not exist.")

    with open(file_name, "rb") as torrent_file:
        bencoded_content = torrent_file.read()

    torrent, _ = decode_bencode(bencoded_content)
    info_hash = calculate_info_hash(torrent[b"info"])
    print("Tracker URL:", torrent[b"announce"].decode(ENCODING))
    print("Length:", torrent[b"info"][b"length"])
    print("Info Hash:", info_hash)
    print("Piece Length:", torrent[b"info"][b"piece length"])
    pieces = torrent[b"info"][b"pieces"]
    piece_hashes = [pieces[i : i + 20].hex() for i in range(0, len(pieces), 20)]
    print("Piece Hashes: ")
    for hash in piece_hashes:
        print(hash)


def main() -> None:
    """Main function to handle command-line interface."""
    parser = argparse.ArgumentParser(
        description="Bencode decoder and torrent info extractor."
    )
    parser.add_argument(
        "command", choices=["decode", "info"], help="Command to execute"
    )
    parser.add_argument("input", help="Bencoded value or torrent file path")

    args = parser.parse_args()

    try:
        if args.command == "decode":
            decode_command(args.input)
        elif args.command == "info":
            info_command(args.input)
    except (BencodeDecodeError, ValueError, FileNotFoundError) as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
