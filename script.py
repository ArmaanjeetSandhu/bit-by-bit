import json
import socket
import sys
from typing import Any, Dict, List, Union

from utils import (
    PeerConnection,
    TorrentFile,
    Tracker,
    decode_bencode,
    download_and_verify_piece,
    download_file,
    download_file_from_metadata,
    download_piece_with_retry,
    get_piece_hashes,
    parse_magnet_link,
    retrieve_metadata_from_trackers,
)

BencodeType = Union[str, int, List[Any], Dict[str, Any]]


def main():
    command = sys.argv[1]

    if command == "decode":
        bencoded_value = sys.argv[2]

        def bytes_to_str(data):
            if isinstance(data, bytes):
                return data.decode()
            raise TypeError(f"Type not serializable: {type(data)}")

        print(json.dumps(decode_bencode(bencoded_value), default=bytes_to_str))

    elif command == "info":
        file_name = sys.argv[2]
        torrent = TorrentFile(file_name)

        # Print the required information
        print("Tracker URL:", torrent.tracker_url)
        print("Length:", torrent.file_length)
        print("Info Hash:", torrent.info_hash_hex)
        print("Piece Length:", torrent.piece_length)
        print("Piece Hashes:")
        for hash_value in torrent.piece_hashes:
            print(hash_value)

    elif command == "peers":
        file_name = sys.argv[2]
        torrent = TorrentFile(file_name)

        # Get peers from tracker
        tracker = Tracker(torrent.tracker_url)
        peers = tracker.get_peers(torrent.info_hash_bytes, torrent.file_length)

        # Print peer addresses
        for peer_addr in peers:
            print(peer_addr)

    elif command == "handshake":
        file_name = sys.argv[2]
        peer_address = sys.argv[3]
        ip, port_str = peer_address.split(":")
        port = int(port_str)

        # Read and parse the torrent file
        torrent = TorrentFile(file_name)

        # Use a hardcoded peer ID for consistency
        peer_id = b"-PY0001-" + b"0" * 12

        # Create the handshake message
        protocol = b"BitTorrent protocol"
        protocol_length = bytes([len(protocol)])
        reserved = bytes(8)  # 8 zeros

        handshake = (
            protocol_length + protocol + reserved + torrent.info_hash_bytes + peer_id
        )

        # Establish TCP connection and send handshake
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)  # Set a reasonable timeout

        try:
            s.connect((ip, port))
            s.send(handshake)

            # Receive the handshake response
            buffer = b""
            response_length = 68  # Expected complete handshake length

            # Keep reading until we get the complete handshake or timeout
            while len(buffer) < response_length:
                try:
                    chunk = s.recv(response_length - len(buffer))
                    if not chunk:  # Connection closed
                        break
                    buffer += chunk
                except socket.timeout:
                    break

            # Check if we received a complete handshake
            if len(buffer) >= 68:  # Full handshake
                # Extract peer ID (last 20 bytes)
                peer_id_received = buffer[-20:]
                print(f"Peer ID: {peer_id_received.hex()}")
            elif (
                len(buffer) > 48
            ):  # We have at least protocol + reserved + info_hash, but partial peer_id
                # Extract whatever we have of the peer ID
                peer_id_partial = buffer[48:]
                print(f"Peer ID (partial): {peer_id_partial.hex()}")
            else:
                print("Failed to receive peer ID")

        except Exception as e:
            print(f"Handshake failed: {e}")

        finally:
            s.close()

    elif command == "download_piece":
        output_file = sys.argv[3]
        torrent_file = sys.argv[4]
        piece_index = int(sys.argv[5])

        # Download the piece
        download_piece_with_retry(torrent_file, piece_index, output_file)

    elif command == "download":
        output_file = sys.argv[3]
        torrent_file = sys.argv[4]
        download_file(torrent_file, output_file)

    elif command == "magnet_parse":
        magnet_link = sys.argv[2]
        info_hash, trackers = parse_magnet_link(magnet_link)
        print(f"Info Hash: {info_hash}")
        for tracker in trackers:
            print(f"Tracker URL: {tracker}")

    elif command == "magnet_handshake":
        magnet_link = sys.argv[2]

        # Parse the magnet link
        info_hash_hex, trackers = parse_magnet_link(magnet_link)

        # Convert hex info hash to binary
        info_hash_bytes = bytes.fromhex(info_hash_hex)

        # Try each tracker
        success = False
        for tracker_url in trackers:
            try:
                # Create tracker and get peers
                tracker = Tracker(tracker_url)
                # We need to estimate a file size for the tracker request
                estimated_file_size = 79752
                peers = tracker.get_peers(info_hash_bytes, estimated_file_size)

                # Try to connect to a peer
                for peer_addr in peers:
                    try:
                        # Connect with extension support, but only perform handshake
                        peer = PeerConnection(peer_addr, info_hash_bytes)
                        peer.connect(support_extensions=True, handshake_only=True)

                        # Print peer ID
                        print(f"Peer ID: {peer.remote_peer_id.hex()}")

                        # Print metadata extension ID if available
                        metadata_id = peer.get_ut_metadata_id()
                        if metadata_id is not None:
                            print(f"Peer Metadata Extension ID: {metadata_id}")
                            success = True

                        peer.close()

                        if success:
                            break  # Exit peer loop

                    except Exception as e:
                        print(f"Failed to connect to peer {peer_addr}: {e}")

                if success:
                    break  # Exit tracker loop

            except Exception as e:
                print(f"Failed to get peers from tracker {tracker_url}: {e}")

        if not success:
            print("Failed to establish connection with any peer")

    elif command == "magnet_info":
        magnet_link = sys.argv[2]

        # Parse the magnet link
        info_hash_hex, trackers = parse_magnet_link(magnet_link)

        # Try to retrieve metadata from any tracker/peer
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)

        if metadata:
            # Print required information
            print(f"Tracker URL: {tracker_url}")
            print(f"Length: {metadata['length']}")
            print(f"Info Hash: {info_hash_hex}")
            print(f"Piece Length: {metadata['piece length']}")
            print("Piece Hashes:")

            # Extract and print piece hashes
            piece_hashes = get_piece_hashes(metadata["pieces"])
            for hash_value in piece_hashes:
                print(hash_value)
        else:
            print("Failed to retrieve metadata from any peer")

    elif command == "magnet_download_piece":
        output_file = sys.argv[3]
        magnet_link = sys.argv[4]
        piece_index = int(sys.argv[5])

        # Parse the magnet link
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        info_hash_bytes = bytes.fromhex(info_hash_hex)

        # Try to retrieve metadata from any tracker/peer
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)

        if not metadata:
            print("Failed to retrieve metadata from any peer")
            return

        # Extract necessary torrent information
        piece_length = metadata["piece length"]
        file_length = metadata["length"]
        piece_hashes = get_piece_hashes(metadata["pieces"])
        total_pieces = len(piece_hashes)

        # Calculate piece size
        if piece_index == total_pieces - 1:  # Last piece
            piece_size = file_length - (total_pieces - 1) * piece_length
        else:
            piece_size = piece_length

        # Download the piece directly
        # Get peers from tracker
        tracker = Tracker(tracker_url)
        peers = tracker.get_peers(info_hash_bytes, file_length)

        # Try to download from peers
        for peer_addr in peers:
            peer = None
            try:
                peer = PeerConnection(peer_addr, info_hash_bytes)
                peer.connect()

                piece_data = download_and_verify_piece(
                    peer, piece_index, piece_size, piece_hashes[piece_index]
                )

                if piece_data:
                    # Save the piece to output file
                    with open(output_file, "wb") as f:
                        f.write(piece_data)
                    print(f"Piece {piece_index} downloaded to {output_file}")
                    return  # Success

            except Exception as e:
                print(f"Failed to download from peer {peer_addr}: {e}")

            finally:
                if peer:
                    peer.close()

        print("Failed to download piece from any peer")

    elif command == "magnet_download":
        output_file = sys.argv[3]
        magnet_link = sys.argv[4]

        # Parse the magnet link
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        info_hash_bytes = bytes.fromhex(info_hash_hex)

        # Try to retrieve metadata from any tracker/peer
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)

        if not metadata:
            print("Failed to retrieve metadata from any peer")
            return

        # Download the file using the metadata
        success = download_file_from_metadata(
            metadata, info_hash_bytes, tracker_url, output_file
        )

        if not success:
            print("Download failed")

    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
