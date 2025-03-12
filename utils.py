import hashlib
import socket
import struct
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple, Union

BencodeType = Union[str, int, List[Any], Dict[str, Any]]


def generate_peer_id(client_id="-PY0001-", random=True):
    """
    Generate a 20-byte peer ID for BitTorrent communication.

    Args:
        client_id (str): The client identifier prefix (default: "-PY0001-")
                        Should be 8 characters: -XX0000- format where XX is client code
        random (bool): Whether to generate a random ID or use zeros (default: True)

    Returns:
        bytes: A 20-byte peer ID

    The BitTorrent spec typically uses a format like:
    -XX0000-123456789012 (20 bytes total)
    Where:
    - First 8 bytes identify the client (-XX0000-)
    - Remaining 12 bytes are usually random or contain version info
    """

    # Ensure client_id is 8 characters
    if len(client_id) != 8:
        raise ValueError("Client ID prefix must be 8 characters long")

    # Create prefix bytes
    prefix = client_id.encode("ascii")

    # Generate the random or zero-filled suffix (12 bytes)
    if random:
        # Generate random bytes for the remaining 12 bytes
        suffix = bytes(random.randint(0, 255) for _ in range(12))
    else:
        # Use zeros for deterministic IDs
        suffix = b"0" * 12

    # Combine prefix and suffix to form 20-byte peer ID
    return prefix + suffix


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


def get_peers_from_tracker(tracker_url, info_hash, file_length):
    """
    Get a list of peers from the tracker.

    Args:
        tracker_url (str): URL of the tracker
        info_hash (bytes): Binary info hash
        file_length (int): Length of the file

    Returns:
        List[str]: List of peer addresses in the format "ip:port"
    """
    # Prepare query parameters
    params = {
        "info_hash": info_hash,
        "peer_id": generate_peer_id(client_id="-PY0001").decode("latin1"),
        "port": 6881,
        "uploaded": 0,
        "downloaded": 0,
        "left": file_length,
        "compact": 1,
    }

    # Construct the URL with parameters
    query_string = "&".join(
        [
            f"{k}={urllib.parse.quote_from_bytes(v) if isinstance(v, bytes) else urllib.parse.quote(str(v))}"
            for k, v in params.items()
        ]
    )
    full_url = f"{tracker_url}?{query_string}"

    # Make the GET request
    response = urllib.request.urlopen(full_url)
    response_data = response.read()

    # Decode the bencoded response
    response_string = response_data.decode("latin1")
    decoded_response = decode_bencode(response_string)

    # Extract peers data
    peers = decoded_response["peers"]
    peers_binary = peers.encode("latin1")  # Convert to binary

    # Parse peers (each peer is 6 bytes: 4 for IP, 2 for port)
    peer_addresses = []
    for i in range(0, len(peers_binary), 6):
        if i + 6 <= len(peers_binary):
            peer_data = peers_binary[i : i + 6]
            ip = socket.inet_ntoa(peer_data[:4])
            port = int.from_bytes(peer_data[4:6], byteorder="big")
            peer_addresses.append(f"{ip}:{port}")

    return peer_addresses


def download_piece_from_peer(
    peer_addr, info_hash, piece_index, piece_size, piece_length
):
    """
    Download a specific piece from a peer.

    Args:
        peer_addr (str): Peer address in the format "ip:port"
        info_hash (bytes): Binary info hash
        piece_index (int): Index of the piece to download
        piece_size (int): Size of the piece in bytes
        piece_length (int): Standard piece length in the torrent

    Returns:
        bytes: The downloaded piece data
    """
    ip, port_str = peer_addr.split(":")
    port = int(port_str)

    # Generate a random peer ID
    peer_id = generate_peer_id()

    # Create the handshake message
    protocol = b"BitTorrent protocol"
    protocol_length = bytes([len(protocol)])
    reserved = bytes(8)
    handshake = protocol_length + protocol + reserved + info_hash + peer_id

    # Establish TCP connection
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(30)  # 30 second timeout
    try:
        s.connect((ip, port))

        # Send handshake
        s.send(handshake)

        # Receive handshake response (should be 68 bytes)
        response = recvall(s, 68)
        if len(response) != 68:
            raise ValueError(
                f"Expected 68 bytes handshake response, got {len(response)} bytes"
            )

        # Wait for bitfield message
        message_length, message_id, _ = receive_message(s)
        if message_id != 5:  # bitfield message id
            raise ValueError(
                f"Expected bitfield message (id 5), got message id {message_id}"
            )

        # Send interested message
        send_message(s, 2, b"")  # message id 2 for interested

        # Wait for unchoke message
        message_length, message_id, _ = receive_message(s)
        if message_id != 1:  # unchoke message id
            raise ValueError(
                f"Expected unchoke message (id 1), got message id {message_id}"
            )

        # Calculate number of blocks and block size
        block_size = 2**14  # 16 KiB
        num_blocks = (piece_size + block_size - 1) // block_size

        # Prepare to store piece data
        piece_data = bytearray(piece_size)

        # Request each block
        for block_index in range(num_blocks):
            # Calculate block offset and length
            block_offset = block_index * block_size
            block_length = min(block_size, piece_size - block_offset)

            # Send request message
            payload = struct.pack(">III", piece_index, block_offset, block_length)
            send_message(s, 6, payload)  # message id 6 for request

            # Receive piece message
            _, message_id, payload = receive_message(s)
            if message_id != 7:  # piece message id
                raise ValueError(
                    f"Expected piece message (id 7), got message id {message_id}"
                )

            # Parse the piece message payload
            index, begin = struct.unpack(">II", payload[:8])
            block_data = payload[8:]

            # Verify index and begin values
            if index != piece_index or begin != block_offset:
                raise ValueError(
                    f"Piece message mismatch. Expected index={piece_index}, begin={block_offset}, got index={index}, begin={begin}"
                )

            # Store the block data
            piece_data[block_offset : block_offset + len(block_data)] = block_data

        return bytes(piece_data)
    finally:
        s.close()


def download_piece(torrent_file, piece_index, output_file):
    """
    Download a specific piece from a torrent and save it to the output file.

    Args:
        torrent_file (str): Path to the torrent file
        piece_index (int): Index of the piece to download
        output_file (str): Path to save the downloaded piece
    """
    # Read and parse the torrent file
    with open(torrent_file, "rb") as f:
        bencoded_data = f.read()
        bencoded_string = bencoded_data.decode("latin1", errors="replace")
        torrent = decode_bencode(bencoded_string)

    # Extract necessary information
    tracker_url = torrent["announce"]
    info_dict = torrent["info"]
    piece_length = info_dict["piece length"]
    file_length = info_dict["length"]

    # Calculate info hash (binary form for peer communication)
    encoded_info = bencode(info_dict)
    info_hash = hashlib.sha1(encoded_info).digest()

    # Get the piece hashes
    piece_hashes = get_piece_hashes(info_dict["pieces"])
    if piece_index >= len(piece_hashes):
        raise ValueError(
            f"Piece index {piece_index} out of range. Only {len(piece_hashes)} pieces available."
        )

    expected_piece_hash = piece_hashes[piece_index]

    # Calculate the actual length of the requested piece
    total_pieces = (file_length + piece_length - 1) // piece_length
    if piece_index == total_pieces - 1:  # Last piece
        piece_size = file_length - (total_pieces - 1) * piece_length
    else:
        piece_size = piece_length

    # Get peers from tracker
    peers = get_peers_from_tracker(tracker_url, info_hash, file_length)

    # Try to download from peers
    for peer_addr in peers:
        try:
            piece_data = download_piece_from_peer(
                peer_addr, info_hash, piece_index, piece_size, piece_length
            )

            # Verify the piece hash
            piece_hash = hashlib.sha1(piece_data).hexdigest()
            if piece_hash != expected_piece_hash:
                print(
                    f"Piece hash verification failed. Expected: {expected_piece_hash}, Got: {piece_hash}"
                )
                continue

            # Save the piece to output file
            with open(output_file, "wb") as f:
                f.write(piece_data)

            print(f"Piece {piece_index} downloaded to {output_file}")
            return True
        except Exception as e:
            print(f"Failed to download from peer {peer_addr}: {e}")

    print("Failed to download piece from any peer")
    return False


def create_handshake_message(info_hash, peer_id, support_extensions=False):
    """
    Create a BitTorrent handshake message.

    Args:
        info_hash (bytes): The 20-byte info hash
        peer_id (bytes): The 20-byte peer ID
        support_extensions (bool): Whether to indicate support for extensions

    Returns:
        bytes: The handshake message
    """
    protocol = b"BitTorrent protocol"
    protocol_length = bytes([len(protocol)])

    # Create reserved bytes
    reserved = bytearray(8)  # 8 bytes (64 bits) of zeros

    # Set the extension bit if requested (20th bit from right)
    if support_extensions:
        # Set the reserved bytes according to the spec: 00 00 00 00 00 10 00 00
        reserved[5] = 0x10

    # Convert reserved bytearray to bytes
    reserved = bytes(reserved)

    # Construct the handshake message
    handshake = protocol_length + protocol + reserved + info_hash + peer_id

    return handshake


def handshake_with_peer(peer_addr, info_hash, support_extensions=False):
    """
    Connect to a peer and perform a handshake.

    Args:
        peer_addr (str): Peer address in the format "ip:port"
        info_hash (bytes): Binary info hash
        support_extensions (bool): Whether to indicate support for extensions

    Returns:
        bytes: The peer ID received during the handshake
    """
    ip, port_str = peer_addr.split(":")
    port = int(port_str)

    # Generate a random peer ID
    peer_id = generate_peer_id()

    # Create the handshake message with extension support if requested
    handshake = create_handshake_message(info_hash, peer_id, support_extensions)

    # Establish TCP connection and send handshake
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)  # 10 second timeout

    try:
        s.connect((ip, port))
        s.send(handshake)

        # Receive handshake response
        response = recvall(s, 68)  # A complete handshake is 68 bytes

        # Extract and return peer ID (last 20 bytes)
        response_peer_id = response[-20:]
        return response_peer_id
    finally:
        s.close()
