import hashlib
import socket
import struct
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple, Union

BencodeType = Union[str, int, List[Any], Dict[str, Any]]


class TorrentFile:
    """Class to handle torrent file operations"""

    def __init__(self, file_path):
        """Initialize from a .torrent file path"""
        with open(file_path, "rb") as f:
            bencoded_data = f.read()
            bencoded_string = bencoded_data.decode("latin1", errors="replace")
            self.torrent = decode_bencode(bencoded_string)

        self.info_dict = self.torrent["info"]
        self.piece_length = self.info_dict["piece length"]
        self.file_length = self.info_dict["length"]

        # Calculate info hash
        encoded_info = bencode(self.info_dict)
        self.info_hash_bytes = hashlib.sha1(encoded_info).digest()
        self.info_hash_hex = hashlib.sha1(encoded_info).hexdigest()

        # Get piece hashes
        self.piece_hashes = get_piece_hashes(self.info_dict["pieces"])
        self.total_pieces = len(self.piece_hashes)

    @property
    def tracker_url(self):
        """Get the tracker URL"""
        return self.torrent["announce"]

    def get_piece_size(self, piece_index):
        """Calculate the size of a specific piece"""
        if piece_index == self.total_pieces - 1:  # Last piece
            return self.file_length - (self.total_pieces - 1) * self.piece_length
        return self.piece_length

    def verify_piece(self, piece_index, piece_data):
        """Verify a piece's hash"""
        piece_hash = hashlib.sha1(piece_data).hexdigest()
        return piece_hash == self.piece_hashes[piece_index]


class PeerConnection:
    """Class to handle BitTorrent peer connections"""

    def __init__(self, peer_addr, info_hash):
        """Initialize a peer connection"""
        self.peer_addr = peer_addr
        self.info_hash = info_hash
        self.peer_id = generate_peer_id()
        self.socket = None
        self.connected = False
        self.remote_peer_id = None
        self.extensions_enabled = False
        self.peer_supports_extensions = False
        self.extension_ids = {}
        self.metadata = None

    def connect(self, support_extensions=False, handshake_only=False):
        """Connect to the peer and perform handshake

        Args:
            support_extensions (bool): Whether to enable extension protocol support
            handshake_only (bool): If True, only perform the handshake without expecting
                                   the regular BitTorrent protocol flow
        """
        ip, port_str = self.peer_addr.split(":")
        port = int(port_str)

        # Create socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(30)  # 30 second timeout

        try:
            self.socket.connect((ip, port))

            # Perform handshake with extension support if requested
            handshake_response = self._perform_handshake(support_extensions)
            self.extensions_enabled = support_extensions

            # Check if peer supports extension protocol
            self.peer_supports_extensions = self._check_peer_supports_extensions(
                handshake_response
            )

            # If peer supports extensions and we're also supporting them, send extension handshake
            if self.peer_supports_extensions and support_extensions:
                self._send_extension_handshake()

                # Try to receive extension handshake
                self._receive_extension_handshake()

            # If we only need to perform the handshake, return now
            if handshake_only:
                self.connected = True
                return True

            # Continue with regular BitTorrent protocol flow
            # Wait for the bitfield message
            message_length, message_id, payload = self._receive_message()

            # Now expect the bitfield message
            if message_id != 5:  # bitfield message id
                raise ValueError(
                    f"Expected bitfield message (id 5), got message id {message_id}"
                )

            # Send interested message
            self._send_message(2, b"")  # message id 2 for interested

            # Wait for unchoke message
            message_length, message_id, _ = self._receive_message()
            if message_id != 1:  # unchoke message id
                raise ValueError(
                    f"Expected unchoke message (id 1), got message id {message_id}"
                )

            self.connected = True
            return True
        except Exception as e:
            self.close()
            raise e

    def _perform_handshake(self, support_extensions=False):
        """Perform the BitTorrent handshake"""
        # Create handshake message
        protocol = b"BitTorrent protocol"
        protocol_length = bytes([len(protocol)])

        # Set up reserved bytes (8 bytes / 64 bits)
        reserved = bytearray(8)  # Start with all zeros

        # Set the 20th bit from the right to 1 if extensions support is enabled
        if support_extensions:
            # This corresponds to: 00 00 00 00 00 10 00 00
            reserved[5] = (
                0x10  # Set the 6th byte to 0x10 (16 in decimal, 00010000 in binary)
            )

        # Convert reserved bytearray to bytes
        reserved = bytes(reserved)

        handshake = (
            protocol_length + protocol + reserved + self.info_hash + self.peer_id
        )

        # Send handshake
        self.socket.send(handshake)

        # Receive handshake response
        response = self._recvall(68)  # A complete handshake is 68 bytes
        if len(response) != 68:
            raise ValueError(
                f"Expected 68 bytes handshake response, got {len(response)} bytes"
            )

        # Extract peer ID (last 20 bytes)
        self.remote_peer_id = response[-20:]
        return response

    def _check_peer_supports_extensions(self, handshake_response):
        """Check if peer supports extension protocol based on handshake response"""
        # Extract reserved bytes (bytes 20-27)
        reserved_bytes = handshake_response[20:28]

        # Check if 20th bit from right is set (bit 0 of byte 5, counting from 0)
        # This corresponds to: 00 00 00 00 00 10 00 00
        return (reserved_bytes[5] & 0x10) != 0

    def _send_extension_handshake(self):
        """Send extension protocol handshake"""
        # Create extension handshake dictionary
        # Using ID 1 for ut_metadata extension (can be any value from 1-255)
        extension_dict = {"m": {"ut_metadata": 1}}  # ID for metadata extension

        # Bencode the dictionary
        payload = bencode(extension_dict)

        # Extension message ID 0 means it's a handshake
        ext_payload = bytes([0]) + payload

        # Send as extension message (ID 20)
        self._send_message(20, ext_payload)

    def _receive_extension_handshake(self):
        """Receive and process extension handshake from peer"""
        try:
            # Set a shorter timeout for extension handshake
            old_timeout = self.socket.gettimeout()
            self.socket.settimeout(10)  # 10 second timeout for extension handshake

            # Try to receive the extension handshake
            message_length, message_id, payload = self._receive_message()

            # If the message is not an extension message, try one more time
            if message_id != 20:
                print(
                    f"Received non-extension message (id {message_id}), trying again..."
                )
                message_length, message_id, payload = self._receive_message()

            # If we received an extension message, process it
            if message_id == 20:
                self._process_extension_message(payload)
            else:
                print(
                    f"Expected extension message (id 20), got message id {message_id}"
                )

        except Exception as e:
            print(f"Error receiving extension handshake: {e}")
        finally:
            # Restore the original timeout
            self.socket.settimeout(old_timeout)

    def _process_extension_message(self, payload):
        """Process an extension protocol message"""
        if not payload:
            raise ValueError("Empty extension message payload")

        # First byte is the extension message ID
        ext_msg_id = payload[0]
        ext_payload = payload[1:]

        # Extension message ID 0 means it's a handshake
        if ext_msg_id == 0:
            # Convert binary payload to string for decoding
            ext_payload_str = ext_payload.decode("latin1")

            # Decode the bencoded dictionary
            handshake_dict = decode_bencode(ext_payload_str)

            # Extract extension IDs if present
            if "m" in handshake_dict:
                self.extension_ids = handshake_dict["m"]
                print(f"Received extension IDs: {self.extension_ids}")

    def get_ut_metadata_id(self):
        """Get the ut_metadata extension ID"""
        if "ut_metadata" in self.extension_ids:
            return self.extension_ids["ut_metadata"]
        return None

    def _recvall(self, n):
        """Receive exactly n bytes from the socket"""
        data = b""
        while len(data) < n:
            packet = self.socket.recv(n - len(data))
            if not packet:
                raise ValueError("Connection closed while receiving data")
            data += packet
        return data

    def _send_message(self, message_id, payload):
        """Send a peer message"""
        # Calculate message length (1 byte for message id + payload length)
        message_length = len(payload) + 1

        # Construct the message
        message = struct.pack(">I", message_length) + bytes([message_id]) + payload

        # Send the message
        self.socket.send(message)

    def _receive_message(self):
        """Receive a peer message"""
        # Receive message length prefix (4 bytes)
        length_prefix = self._recvall(4)

        # Parse message length
        message_length = struct.unpack(">I", length_prefix)[0]

        # Check for keep-alive message (length = 0)
        if message_length == 0:
            return 0, None, b""

        # Receive the rest of the message
        message = self._recvall(message_length)

        # Parse message ID and payload
        message_id = message[0]
        payload = message[1:] if len(message) > 1 else b""

        return message_length, message_id, payload

    def download_piece(self, piece_index, piece_size):
        """Download a specific piece"""
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
            self._send_message(6, payload)  # message id 6 for request

            # Receive piece message
            _, message_id, payload = self._receive_message()
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

    def send_metadata_request(self, piece=0):
        """Send a metadata extension request message.

        Args:
            piece (int): The piece index to request (default: 0)
        """
        # Get the metadata extension ID
        metadata_id = self.get_ut_metadata_id()
        if metadata_id is None:
            raise ValueError("Peer does not support ut_metadata extension")

        # Create the request dictionary
        request_dict = {"msg_type": 0, "piece": piece}

        # Bencode the dictionary
        payload = bencode(request_dict)

        # Construct the complete message
        # extension_id + bencoded_dict
        ext_payload = bytes([metadata_id]) + payload

        # Send as extension message (ID 20)
        self._send_message(20, ext_payload)
        print(f"Sent metadata request for piece {piece}")

    def receive_metadata_response(self):
        """Receive and process metadata extension response.

        Returns:
            dict: The decoded metadata info dictionary
        """
        # Wait for metadata response
        message_length, message_id, payload = self._receive_message()

        if message_id != 20:  # Not an extension message
            raise ValueError(
                f"Expected extension message (id 20), got message id {message_id}"
            )

        # Skip the extension message ID (first byte)
        ext_payload = payload[1:]

        # The extension payload contains:
        # 1. A bencoded dictionary with msg_type, piece, total_size
        # 2. The raw metadata bytes

        # Convert to string for processing
        ext_payload_str = ext_payload.decode("latin1")

        # Look for the second 'd' character, which should be the start of the metadata
        # This is where the actual metadata dictionary begins
        second_dict_start = ext_payload_str.find("d", 1)

        if second_dict_start == -1:
            raise ValueError("Could not find start of metadata dictionary")

        # Extract metadata
        metadata_str = ext_payload_str[second_dict_start:]

        # Parse metadata
        metadata = decode_bencode(metadata_str)

        # Store the metadata
        self.metadata = metadata
        return metadata

    def retrieve_metadata(self):
        """Retrieve metadata using extension protocol.

        Returns:
            dict: The metadata info dictionary or None if retrieval failed
        """
        if not self.peer_supports_extensions:
            return None

        metadata_id = self.get_ut_metadata_id()
        if metadata_id is None:
            return None

        try:
            # Send metadata request
            self.send_metadata_request()

            # Receive metadata response
            metadata = self.receive_metadata_response()

            # Verify the info hash
            encoded_metadata = bencode(metadata)
            metadata_hash = hashlib.sha1(encoded_metadata).digest()

            if metadata_hash != self.info_hash:
                print(
                    f"Info hash mismatch. Expected {self.info_hash.hex()}, got {metadata_hash.hex()}"
                )
                return None

            return metadata
        except Exception as e:
            print(f"Failed to retrieve metadata: {e}")
            return None

    def close(self):
        """Close the connection"""
        if self.socket:
            self.socket.close()
            self.socket = None
            self.connected = False


class Tracker:
    """Class to handle BitTorrent tracker communication"""

    def __init__(self, tracker_url):
        """Initialize with tracker URL"""
        self.tracker_url = tracker_url

    def get_peers(self, info_hash, file_length, peer_id=None):
        """Get a list of peers from the tracker"""
        if peer_id is None:
            peer_id = generate_peer_id(client_id="-PY0001-")

        # Prepare query parameters
        params = {
            "info_hash": info_hash,
            "peer_id": peer_id,
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
        full_url = f"{self.tracker_url}?{query_string}"

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


def generate_peer_id(client_id="-PY0001-", random_bytes=True):
    """
    Generate a 20-byte peer ID for BitTorrent communication.

    Args:
        client_id (str): The client identifier prefix (default: "-PY0001-")
                        Should be 8 characters: -XX0000- format where XX is client code
        random_bytes (bool): Whether to generate random bytes or use zeros (default: True)

    Returns:
        bytes: A 20-byte peer ID
    """
    import random as rand

    # Ensure client_id is 8 characters
    if len(client_id) != 8:
        raise ValueError("Client ID prefix must be 8 characters long")

    # Create prefix bytes
    prefix = client_id.encode("ascii")

    # Generate the random or zero-filled suffix (12 bytes)
    if random_bytes:
        # Generate random bytes for the remaining 12 bytes
        suffix = bytes(rand.randint(0, 255) for _ in range(12))
    else:
        # Use zeros for deterministic IDs
        suffix = b"0" * 12

    # Combine prefix and suffix to form 20-byte peer ID
    return prefix + suffix


def decode_bencode(bdata: str) -> BencodeType:
    """Decode a bencoded string."""

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
    """Encode data into a bencoded byte string."""
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
    """Split concatenated piece hashes into individual SHA1 hashes."""
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


def download_piece_with_retry(torrent_file, piece_index, output_file=None):
    """Download a specific piece from any available peer"""
    torrent = (
        torrent_file
        if isinstance(torrent_file, TorrentFile)
        else TorrentFile(torrent_file)
    )

    # Get the piece size
    piece_size = torrent.get_piece_size(piece_index)

    # Get peers from tracker
    tracker = Tracker(torrent.tracker_url)
    peers = tracker.get_peers(torrent.info_hash_bytes, torrent.file_length)

    # Try to download from peers
    for peer_addr in peers:
        peer = None
        try:
            peer = PeerConnection(peer_addr, torrent.info_hash_bytes)
            peer.connect()

            piece_data = peer.download_piece(piece_index, piece_size)

            # Verify the piece hash
            if not torrent.verify_piece(piece_index, piece_data):
                print(f"Piece hash verification failed for piece {piece_index}")
                continue

            # Save the piece to output file if provided
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(piece_data)
                print(f"Piece {piece_index} downloaded to {output_file}")

            return piece_data
        except Exception as e:
            print(f"Failed to download from peer {peer_addr}: {e}")
        finally:
            if peer:
                peer.close()

    print("Failed to download piece from any peer")
    return None


def download_file(torrent_file, output_file):
    """Download a complete file from a torrent"""
    torrent = (
        torrent_file
        if isinstance(torrent_file, TorrentFile)
        else TorrentFile(torrent_file)
    )

    # Create the output file
    with open(output_file, "wb") as f:
        f.truncate(torrent.file_length)  # Pre-allocate the file size

    # Get peers from tracker
    tracker = Tracker(torrent.tracker_url)
    peers = tracker.get_peers(torrent.info_hash_bytes, torrent.file_length)

    if not peers:
        print("No peers available")
        return False

    # Try to download from each peer
    for peer_addr in peers:
        peer = None
        try:
            print(f"Connecting to peer {peer_addr}...")
            peer = PeerConnection(peer_addr, torrent.info_hash_bytes)
            peer.connect()

            # Download each piece
            for piece_index in range(torrent.total_pieces):
                piece_size = torrent.get_piece_size(piece_index)

                print(f"Downloading piece {piece_index + 1}/{torrent.total_pieces}...")

                piece_data = peer.download_piece(piece_index, piece_size)

                # Verify the piece hash
                if not torrent.verify_piece(piece_index, piece_data):
                    print(f"Piece {piece_index} hash verification failed")
                    raise ValueError("Hash verification failed")

                # Write the piece to the output file
                with open(output_file, "r+b") as f:
                    f.seek(piece_index * torrent.piece_length)
                    f.write(piece_data)

                print(
                    f"Piece {piece_index + 1}/{torrent.total_pieces} downloaded and verified"
                )

            # All pieces downloaded successfully
            print(f"File downloaded to {output_file}")
            return True

        except Exception as e:
            print(f"Failed to download from peer {peer_addr}: {e}")
            # Continue with the next peer
        finally:
            if peer:
                peer.close()

    # All peers failed
    print("Failed to download file from any peer")
    return False


def parse_magnet_link(magnet_link):
    """Parse a magnet link and extract the info hash and tracker URLs."""
    # Check if the link starts with "magnet:"
    if not magnet_link.startswith("magnet:?"):
        raise ValueError("Not a valid magnet link")

    # Parse the query parameters
    query_string = magnet_link[8:]  # Remove "magnet:?" prefix
    params = urllib.parse.parse_qs(query_string)

    # Extract the info hash from xt parameter (urn:btih:<info-hash>)
    info_hash = None
    for xt in params.get("xt", []):
        if xt.startswith("urn:btih:"):
            info_hash = xt[
                9:
            ].lower()  # Remove "urn:btih:" prefix and convert to lowercase
            break

    if not info_hash:
        raise ValueError("No valid info hash found in magnet link")

    # Extract tracker URLs (they are already URL-decoded by parse_qs)
    trackers = params.get("tr", [])

    return info_hash, trackers


def retrieve_metadata_from_trackers(info_hash_hex, trackers):
    """
    Retrieve metadata from peers using extension protocol.

    Args:
        info_hash_hex (str): Hex string representation of info hash
        trackers (list): List of tracker URLs

    Returns:
        tuple: (metadata, tracker_url) or (None, None) if metadata retrieval failed
    """
    info_hash_bytes = bytes.fromhex(info_hash_hex)

    for tracker_url in trackers:
        try:
            # Create tracker and get peers
            tracker = Tracker(tracker_url)
            estimated_file_size = 79752  # Estimate for tracker request
            peers = tracker.get_peers(info_hash_bytes, estimated_file_size)

            # Try to connect to each peer
            for peer_addr in peers:
                try:
                    peer = PeerConnection(peer_addr, info_hash_bytes)

                    # Create socket and connect with extension support
                    ip, port_str = peer_addr.split(":")
                    port = int(port_str)

                    peer.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    peer.socket.settimeout(30)
                    peer.socket.connect((ip, port))

                    # Perform handshake with extension support
                    handshake_response = peer._perform_handshake(
                        support_extensions=True
                    )
                    peer.extensions_enabled = True

                    # Check if peer supports extension protocol
                    peer.peer_supports_extensions = (
                        peer._check_peer_supports_extensions(handshake_response)
                    )

                    if not peer.peer_supports_extensions:
                        peer.close()
                        continue

                    # Receive the bitfield message
                    message_length, message_id, _ = peer._receive_message()

                    # Send extension handshake
                    peer._send_extension_handshake()

                    # Wait for extension handshake
                    found_extension = False
                    for _ in range(3):  # Try a few times
                        try:
                            message_length, message_id, payload = (
                                peer._receive_message()
                            )
                            if message_id == 20:  # Extension message
                                peer._process_extension_message(payload)
                                found_extension = True
                                break
                        except Exception as e:
                            print(f"Error receiving message: {e}")
                            break

                    if not found_extension:
                        peer.close()
                        continue

                    # Try to retrieve metadata
                    metadata = peer.retrieve_metadata()

                    if metadata:
                        peer.close()
                        return metadata, tracker_url

                    peer.close()

                except Exception as e:
                    print(f"Failed to connect to peer {peer_addr}: {e}")
                    continue

        except Exception as e:
            print(f"Failed to get peers from tracker {tracker_url}: {e}")
            continue

    return None, None


def download_and_verify_piece(peer, piece_index, piece_size, expected_hash=None):
    """
    Download a piece from a peer and verify its hash.

    Args:
        peer (PeerConnection): Connected peer
        piece_index (int): Index of the piece to download
        piece_size (int): Size of the piece in bytes
        expected_hash (str, optional): Expected SHA1 hash in hex format

    Returns:
        bytes: The downloaded piece data if successful, None otherwise
    """
    try:
        piece_data = peer.download_piece(piece_index, piece_size)

        # Verify the piece hash if an expected hash is provided
        if expected_hash:
            piece_hash = hashlib.sha1(piece_data).hexdigest()
            if piece_hash != expected_hash:
                print(f"Piece hash verification failed for piece {piece_index}")
                print(f"  Expected: {expected_hash}")
                print(f"  Got: {piece_hash}")
                return None

        return piece_data

    except Exception as e:
        print(f"Failed to download piece {piece_index}: {e}")
        return None


def download_file_from_metadata(metadata, info_hash_bytes, tracker_url, output_file):
    """
    Download a complete file using metadata information.

    Args:
        metadata (dict): Metadata dictionary
        info_hash_bytes (bytes): Info hash as bytes
        tracker_url (str): Tracker URL
        output_file (str): Path to save the downloaded file

    Returns:
        bool: True if download was successful, False otherwise
    """
    # Extract necessary torrent information
    piece_length = metadata["piece length"]
    file_length = metadata["length"]
    piece_hashes = get_piece_hashes(metadata["pieces"])
    total_pieces = len(piece_hashes)

    # Create the output file
    with open(output_file, "wb") as f:
        f.truncate(file_length)  # Pre-allocate the file size

    # Get peers from tracker
    tracker = Tracker(tracker_url)
    peers = tracker.get_peers(info_hash_bytes, file_length)

    if not peers:
        print("No peers available")
        return False

    # Download each piece
    downloaded_pieces = 0

    for piece_index in range(total_pieces):
        # Calculate piece size
        if piece_index == total_pieces - 1:  # Last piece
            piece_size = file_length - (total_pieces - 1) * piece_length
        else:
            piece_size = piece_length

        print(f"Downloading piece {piece_index + 1}/{total_pieces}...")

        # Try each peer until the piece is downloaded
        piece_downloaded = False

        for peer_addr in peers:
            peer = None
            try:
                print(f"Trying peer {peer_addr} for piece {piece_index}...")
                peer = PeerConnection(peer_addr, info_hash_bytes)
                peer.connect()

                piece_data = download_and_verify_piece(
                    peer, piece_index, piece_size, piece_hashes[piece_index]
                )

                if piece_data:
                    # Write the piece to the output file
                    with open(output_file, "r+b") as f:
                        f.seek(piece_index * piece_length)
                        f.write(piece_data)

                    print(
                        f"Piece {piece_index + 1}/{total_pieces} downloaded and verified"
                    )
                    piece_downloaded = True
                    downloaded_pieces += 1
                    break  # Piece downloaded successfully, move to the next piece

            except Exception as e:
                print(f"Failed to download from peer {peer_addr}: {e}")

            finally:
                if peer:
                    peer.close()

        if not piece_downloaded:
            print(f"Failed to download piece {piece_index} from any peer")
            return False

    # Check if all pieces were downloaded
    if downloaded_pieces == total_pieces:
        print(f"File downloaded to {output_file}")
        return True
    else:
        print(
            f"Download incomplete: {downloaded_pieces}/{total_pieces} pieces downloaded"
        )
        return False
