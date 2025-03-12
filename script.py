import hashlib
import json
import socket
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Union

from utils import (
    bencode,
    decode_bencode,
    download_piece,
    get_piece_hashes,
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
        with open(file_name, "rb") as torrent_file:
            # Read and decode the torrent file
            bencoded_data = torrent_file.read()
            bencoded_string = bencoded_data.decode("latin1", errors="replace")
            torrent = decode_bencode(bencoded_string)

            # Extract the info dictionary and re-encode it to calculate the info hash
            info_dict = torrent["info"]
            encoded_info = bencode(info_dict)
            info_hash = hashlib.sha1(encoded_info).hexdigest()

            # Get piece length and piece hashes
            piece_length = info_dict["piece length"]
            piece_hashes = get_piece_hashes(info_dict["pieces"])

            # Print the required information
            print("Tracker URL:", torrent["announce"])
            print("Length:", info_dict["length"])
            print("Info Hash:", info_hash)
            print("Piece Length:", piece_length)
            print("Piece Hashes:")
            for hash_value in piece_hashes:
                print(hash_value)
    elif command == "peers":
        file_name = sys.argv[2]
        with open(file_name, "rb") as torrent_file:
            # Read and decode the torrent file
            bencoded_data = torrent_file.read()
            bencoded_string = bencoded_data.decode("latin1", errors="replace")
            torrent = decode_bencode(bencoded_string)

            # Get the tracker URL and info_hash
            tracker_url = torrent["announce"]
            info_dict = torrent["info"]
            file_length = info_dict["length"]

            # Calculate info hash - we need both hex and binary forms
            encoded_info = bencode(info_dict)
            info_hash_hex = hashlib.sha1(encoded_info).hexdigest()
            # Convert hex to binary (20 bytes)
            info_hash_bin = bytes.fromhex(info_hash_hex)

            # Prepare query parameters
            params = {
                "info_hash": info_hash_bin,  # 20 bytes binary
                "peer_id": "-CC0001-" + "0" * 12,  # 20 char string
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

            # Parse and print peers (each peer is 6 bytes: 4 for IP, 2 for port)
            for i in range(0, len(peers_binary), 6):
                if i + 6 <= len(peers_binary):
                    peer_data = peers_binary[i : i + 6]
                    ip = socket.inet_ntoa(
                        peer_data[:4]
                    )  # Convert 4 bytes to IP address
                    port = int.from_bytes(
                        peer_data[4:6], byteorder="big"
                    )  # Convert 2 bytes to port
                    print(f"{ip}:{port}")
    elif command == "handshake":
        file_name = sys.argv[2]
        peer_address = sys.argv[3]
        ip, port_str = peer_address.split(":")
        port = int(port_str)

        # Read and parse the torrent file
        with open(file_name, "rb") as torrent_file:
            bencoded_data = torrent_file.read()
            bencoded_string = bencoded_data.decode("latin1", errors="replace")
            torrent = decode_bencode(bencoded_string)

        # Calculate the info hash
        info_dict = torrent["info"]
        encoded_info = bencode(info_dict)
        info_hash = hashlib.sha1(encoded_info).digest()  # Binary format (20 bytes)

        # Generate a random peer ID (20 bytes)
        import random

        peer_id = bytes(random.randint(0, 255) for _ in range(20))

        # Create the handshake message
        protocol = b"BitTorrent protocol"
        protocol_length = bytes([len(protocol)])  # Single byte with value 19
        reserved = bytes(8)  # 8 zeros

        handshake = protocol_length + protocol + reserved + info_hash + peer_id

        # Establish TCP connection and send handshake
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((ip, port))
            s.send(handshake)

            # Receive handshake response
            response = s.recv(68)  # A complete handshake is 68 bytes

            # Extract and print peer ID (last 20 bytes)
            response_peer_id = response[-20:]
            print(f"Peer ID: {response_peer_id.hex()}")
        finally:
            # Close the connection
            s.close()
    elif command == "download_piece":
        output_file = sys.argv[3]
        torrent_file = sys.argv[4]
        piece_index = int(sys.argv[5])
        download_piece(torrent_file, piece_index, output_file)
    # elif command == "download":
    #     output_file = sys.argv[3]
    #     torrent_file = sys.argv[4]
    #     download_file(torrent_file, output_file)
    else:
        raise NotImplementedError(f"Unknown command {command}")


if __name__ == "__main__":
    main()
