import struct
from typing import Any, Dict, List, Tuple, Union

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


def bencode(data: Any) -> bytes:
    """
    Encode data into a bencoded byte string.

    Args:
        data: The data to encode

    Returns:
        bytes: The bencoded data
    """
    if isinstance(data, str):
        # Convert string to bytes using latin1 encoding to handle binary data correctly
        data_bytes = data.encode("latin1")
        return f"{len(data)}:".encode("ascii") + data_bytes
    elif isinstance(data, int):
        return f"i{data}e".encode("ascii")
    elif isinstance(data, list):
        result = b"l"
        for item in data:
            result += bencode(item)
        result += b"e"
        return result
    elif isinstance(data, dict):
        result = b"d"
        # Sort keys for consistent ordering
        for key in sorted(data.keys()):
            result += bencode(key)
            result += bencode(data[key])
        result += b"e"
        return result
    else:
        raise TypeError(f"Cannot bencode data of type {type(data)}")


def get_piece_hashes(pieces: str) -> List[str]:
    """
    Split concatenated piece hashes into individual SHA1 hashes.

    Args:
        pieces (str): The concatenated piece hashes

    Returns:
        List[str]: List of SHA1 hashes as hex strings
    """
    # Convert string to bytes using latin1 encoding (preserves byte values)
    pieces_bytes = pieces.encode("latin1")

    # Each SHA1 hash is 20 bytes
    hash_size = 20

    # Split into 20-byte chunks and convert each to hex
    hashes = []
    for i in range(0, len(pieces_bytes), hash_size):
        piece_hash = pieces_bytes[i : i + hash_size]
        hex_hash = piece_hash.hex()
        hashes.append(hex_hash)

    return hashes


def recvall(sock, n):
    """
    Receive exactly n bytes from a socket.

    Args:
        sock (socket.socket): Socket to receive from
        n (int): Number of bytes to receive

    Returns:
        bytes: Received data
    """
    data = b""
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            raise ValueError("Connection closed while receiving data")
        data += packet
    return data


def send_message(sock, message_id, payload):
    """
    Send a peer message.

    Args:
        sock (socket.socket): Socket to send the message through
        message_id (int): ID of the message
        payload (bytes): Payload of the message
    """
    # Calculate message length (1 byte for message id + payload length)
    message_length = len(payload) + 1

    # Construct the message
    message = struct.pack(">I", message_length) + bytes([message_id]) + payload

    # Send the message
    sock.send(message)


def receive_message(sock):
    """
    Receive a peer message.

    Args:
        sock (socket.socket): Socket to receive the message from

    Returns:
        Tuple[int, int, bytes]: Message length, message ID, and payload
    """
    # Receive message length prefix (4 bytes)
    length_prefix = recvall(sock, 4)

    # Parse message length
    message_length = struct.unpack(">I", length_prefix)[0]

    # Check for keep-alive message (length = 0)
    if message_length == 0:
        return 0, None, b""

    # Receive the rest of the message
    message = recvall(sock, message_length)

    # Parse message ID and payload
    message_id = message[0]
    payload = message[1:] if len(message) > 1 else b""

    return message_length, message_id, payload
