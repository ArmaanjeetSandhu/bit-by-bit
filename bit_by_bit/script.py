import json
import socket
import sys
from typing import Any, Dict, List, Union

from bit_by_bit.utils import (
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
        tracker = Tracker(torrent.tracker_url)
        peers = tracker.get_peers(torrent.info_hash_bytes, torrent.file_length)
        for peer_addr in peers:
            print(peer_addr)
    elif command == "handshake":
        file_name = sys.argv[2]
        peer_address = sys.argv[3]
        ip, port_str = peer_address.split(":")
        port = int(port_str)
        torrent = TorrentFile(file_name)
        peer_id = b"-PY0001-" + b"0" * 12
        protocol = b"BitTorrent protocol"
        protocol_length = bytes([len(protocol)])
        reserved = bytes(8)
        handshake = (
            protocol_length + protocol + reserved + torrent.info_hash_bytes + peer_id
        )
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        try:
            s.connect((ip, port))
            s.send(handshake)
            buffer = b""
            response_length = 68
            while len(buffer) < response_length:
                try:
                    chunk = s.recv(response_length - len(buffer))
                    if not chunk:
                        break
                    buffer += chunk
                except socket.timeout:
                    break
            if len(buffer) >= 68:
                peer_id_received = buffer[-20:]
                print(f"Peer ID: {peer_id_received.hex()}")
            elif len(buffer) > 48:
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
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        info_hash_bytes = bytes.fromhex(info_hash_hex)
        success = False
        for tracker_url in trackers:
            try:
                tracker = Tracker(tracker_url)
                estimated_file_size = 79752
                peers = tracker.get_peers(info_hash_bytes, estimated_file_size)
                for peer_addr in peers:
                    try:
                        peer = PeerConnection(peer_addr, info_hash_bytes)
                        peer.connect(support_extensions=True, handshake_only=True)
                        print(f"Peer ID: {peer.remote_peer_id.hex()}")
                        metadata_id = peer.get_ut_metadata_id()
                        if metadata_id is not None:
                            print(f"Peer Metadata Extension ID: {metadata_id}")
                            success = True
                        peer.close()
                        if success:
                            break
                    except Exception as e:
                        print(f"Failed to connect to peer {peer_addr}: {e}")
                if success:
                    break
            except Exception as e:
                print(f"Failed to get peers from tracker {tracker_url}: {e}")
        if not success:
            print("Failed to establish connection with any peer")
    elif command == "magnet_info":
        magnet_link = sys.argv[2]
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)
        if metadata:
            print(f"Tracker URL: {tracker_url}")
            print(f"Length: {metadata['length']}")
            print(f"Info Hash: {info_hash_hex}")
            print(f"Piece Length: {metadata['piece length']}")
            print("Piece Hashes:")
            piece_hashes = get_piece_hashes(metadata["pieces"])
            for hash_value in piece_hashes:
                print(hash_value)
        else:
            print("Failed to retrieve metadata from any peer")
    elif command == "magnet_download_piece":
        output_file = sys.argv[3]
        magnet_link = sys.argv[4]
        piece_index = int(sys.argv[5])
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        info_hash_bytes = bytes.fromhex(info_hash_hex)
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)
        if not metadata:
            print("Failed to retrieve metadata from any peer")
            return
        piece_length = metadata["piece length"]
        file_length = metadata["length"]
        piece_hashes = get_piece_hashes(metadata["pieces"])
        total_pieces = len(piece_hashes)
        if piece_index == total_pieces - 1:
            piece_size = file_length - (total_pieces - 1) * piece_length
        else:
            piece_size = piece_length
        tracker = Tracker(tracker_url)
        peers = tracker.get_peers(info_hash_bytes, file_length)
        for peer_addr in peers:
            peer = None
            try:
                peer = PeerConnection(peer_addr, info_hash_bytes)
                peer.connect()
                piece_data = download_and_verify_piece(
                    peer, piece_index, piece_size, piece_hashes[piece_index]
                )
                if piece_data:
                    with open(output_file, "wb") as f:
                        f.write(piece_data)
                    print(f"Piece {piece_index} downloaded to {output_file}")
                    return
            except Exception as e:
                print(f"Failed to download from peer {peer_addr}: {e}")
            finally:
                if peer:
                    peer.close()
        print("Failed to download piece from any peer")
    elif command == "magnet_download":
        output_file = sys.argv[3]
        magnet_link = sys.argv[4]
        info_hash_hex, trackers = parse_magnet_link(magnet_link)
        info_hash_bytes = bytes.fromhex(info_hash_hex)
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash_hex, trackers)
        if not metadata:
            print("Failed to retrieve metadata from any peer")
            return
        success = download_file_from_metadata(
            metadata, info_hash_bytes, tracker_url, output_file
        )
        if not success:
            print("Download failed")
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
