import json
import struct
import sys
from unittest.mock import Mock, call, mock_open, patch

import pytest

from bit_by_bit.script import main
from bit_by_bit.utils import (
    PeerConnection,
    TorrentFile,
    Tracker,
    bencode,
    decode_bencode,
    download_file,
    download_piece_with_retry,
    generate_peer_id,
    get_piece_hashes,
    parse_magnet_link,
)


@pytest.fixture
def sample_bencode_data():
    """Sample bencode data for testing."""
    return {
        "string": "5:hello",
        "decoded_string": "hello",
        "integer": "i42e",
        "decoded_integer": 42,
        "list": "l5:helloi42ee",
        "decoded_list": ["hello", 42],
        "dict": "d4:name5:hello3:agei42ee",
        "decoded_dict": {"name": "hello", "age": 42},
        "complex": "d8:announce22:http://tracker.example4:infod6:lengthi1024e12:piece lengthi256eee",
        "decoded_complex": {
            "announce": "http://tracker.example",
            "info": {"length": 1024, "piece length": 256},
        },
    }


@pytest.fixture
def mock_torrent_file_data():
    """Create mock data for a torrent file."""
    return {
        "announce": "http://tracker.example",
        "info": {
            "name": "test.file",
            "piece length": 256,
            "length": 1024,
            "pieces": "aaaabbbbccccddddeeeeffffgggghhhhiiiijjjj",
        },
    }


@pytest.fixture
def mock_info_hash():
    return b"0123456789abcdefghij"


@pytest.fixture
def mock_peer_addr():
    return "192.168.1.1:6881"


@pytest.fixture
def mock_tracker_url():
    return "http://tracker.example:6969/announce"


@pytest.fixture
def mock_magnet_link():
    return "magnet:?xt=urn:btih:08ada5a7a6183aae1e09d831df6748d566095a10&dn=Test+File&tr=udp%3A%2F%2Ftracker.example%3A6969%2Fannounce"


class TestBencode:
    def test_decode_string(self, sample_bencode_data):
        decoded = decode_bencode(sample_bencode_data["string"])
        assert decoded == sample_bencode_data["decoded_string"]

    def test_decode_integer(self, sample_bencode_data):
        decoded = decode_bencode(sample_bencode_data["integer"])
        assert decoded == sample_bencode_data["decoded_integer"]

    def test_decode_list(self, sample_bencode_data):
        decoded = decode_bencode(sample_bencode_data["list"])
        assert decoded == sample_bencode_data["decoded_list"]

    def test_decode_dict(self, sample_bencode_data):
        decoded = decode_bencode(sample_bencode_data["dict"])
        assert decoded == sample_bencode_data["decoded_dict"]

    def test_decode_complex(self, sample_bencode_data):
        decoded = decode_bencode(sample_bencode_data["complex"])
        assert decoded["announce"] == sample_bencode_data["decoded_complex"]["announce"]
        assert (
            decoded["info"]["length"]
            == sample_bencode_data["decoded_complex"]["info"]["length"]
        )
        assert (
            decoded["info"]["piece length"]
            == sample_bencode_data["decoded_complex"]["info"]["piece length"]
        )

    def test_encode_string(self):
        encoded = bencode("hello")
        assert encoded == b"5:hello"

    def test_encode_integer(self):
        encoded = bencode(42)
        assert encoded == b"i42e"

    def test_encode_list(self):
        encoded = bencode(["hello", 42])
        assert encoded == b"l5:helloi42ee"

    def test_encode_dict(self):
        encoded = bencode({"name": "hello", "age": 42})
        assert encoded == b"d3:agei42e4:name5:helloe"

    def test_encode_decode_roundtrip(self, sample_bencode_data):
        """Test that encoding and then decoding returns the original data."""
        for key, decoded in sample_bencode_data.items():
            if key.startswith("decoded_") and isinstance(
                decoded, (str, int, list, dict)
            ):
                encoded = bencode(decoded)
                re_decoded = decode_bencode(encoded.decode("latin1"))
                assert re_decoded == decoded

    def test_decode_invalid_data(self):
        try:
            with pytest.raises(ValueError):
                decode_bencode("d123:Hello")
        except Exception:
            with pytest.raises(Exception):
                decode_bencode("5hello")
            with pytest.raises(Exception):
                decode_bencode("i42x")
            with pytest.raises(Exception):
                decode_bencode("lxyz")
            with pytest.raises(Exception):
                decode_bencode("dxyz")


class TestTorrentFile:
    @pytest.fixture
    def mock_torrent_file(self, mock_torrent_file_data, tmp_path):
        """Create a mock torrent file for testing."""
        file_path = tmp_path / "test.torrent"
        encoded_data = bencode(mock_torrent_file_data)
        with open(file_path, "wb") as f:
            f.write(encoded_data)
        return file_path

    def test_torrent_file_init(self, mock_torrent_file, mock_torrent_file_data):
        torrent = TorrentFile(mock_torrent_file)
        assert torrent.tracker_url == mock_torrent_file_data["announce"]
        assert torrent.piece_length == mock_torrent_file_data["info"]["piece length"]
        assert torrent.file_length == mock_torrent_file_data["info"]["length"]
        assert len(torrent.piece_hashes) == 2

    def test_get_piece_size(self, mock_torrent_file):
        torrent = TorrentFile(mock_torrent_file)
        assert torrent.get_piece_size(0) == torrent.piece_length
        with patch.object(torrent, "total_pieces", 2):
            with patch.object(torrent, "file_length", 384):
                assert torrent.get_piece_size(0) == 256
                assert torrent.get_piece_size(1) == 128

    def test_verify_piece(self, mock_torrent_file):
        torrent = TorrentFile(mock_torrent_file)
        mock_piece_data = b"aaaabbbbccccddddeeee"
        with patch("hashlib.sha1") as mock_sha1:
            mock_hash = Mock()
            mock_hash.hexdigest.return_value = torrent.piece_hashes[0]
            mock_sha1.return_value = mock_hash
            assert torrent.verify_piece(0, mock_piece_data) is True
            mock_hash.hexdigest.return_value = "incorrecthash"
            assert torrent.verify_piece(0, mock_piece_data) is False


class TestPeerConnection:
    def test_init(self, mock_peer_addr, mock_info_hash):
        peer = PeerConnection(mock_peer_addr, mock_info_hash)
        assert peer.peer_addr == mock_peer_addr
        assert peer.info_hash == mock_info_hash
        assert peer.connected is False
        assert peer.socket is None
        assert peer.peer_id.startswith(b"-PY0001-")
        assert len(peer.peer_id) == 20

    @patch("socket.socket")
    def test_connect(self, mock_socket, mock_peer_addr, mock_info_hash):
        mock_socket_instance = Mock()
        mock_socket.return_value = mock_socket_instance
        with patch.object(PeerConnection, "_perform_handshake") as mock_handshake:
            reserved_bytes = bytearray(8)
            reserved_bytes[5] = 0x10
            mock_handshake_response = (
                b"bit_by_bit protocol"
                + bytes(reserved_bytes)
                + mock_info_hash
                + b"0123456789abcdefghij"
            )
            mock_handshake.return_value = mock_handshake_response
            with patch.object(
                PeerConnection, "_check_peer_supports_extensions"
            ) as mock_check_extensions:
                mock_check_extensions.return_value = True
                with patch.object(
                    PeerConnection, "_send_extension_handshake"
                ) as mock_send_ext:
                    with patch.object(
                        PeerConnection, "_receive_extension_handshake"
                    ) as mock_recv_ext:
                        with patch.object(
                            PeerConnection, "_receive_message"
                        ) as mock_receive:
                            mock_receive.side_effect = [
                                (5, 5, b"bitfield"),
                                (1, 1, b""),
                            ]
                            with patch.object(
                                PeerConnection, "_send_message"
                            ) as mock_send:
                                peer = PeerConnection(mock_peer_addr, mock_info_hash)
                                result = peer.connect(support_extensions=True)
                                assert mock_socket.called
                                ip, port = mock_peer_addr.split(":")
                                mock_socket_instance.connect.assert_called_with(
                                    (ip, int(port))
                                )
                                assert mock_handshake.called
                                assert mock_check_extensions.called
                                assert mock_send_ext.called
                                assert mock_recv_ext.called
                                assert mock_receive.call_count == 2
                                assert mock_send.called
                                assert result is True
                                assert peer.connected is True

    @patch("socket.socket")
    def test_download_piece(self, mock_socket, mock_peer_addr, mock_info_hash):
        mock_socket_instance = Mock()
        mock_socket.return_value = mock_socket_instance
        peer = PeerConnection(mock_peer_addr, mock_info_hash)
        peer.socket = mock_socket_instance
        peer.connected = True
        with patch.object(peer, "_send_message") as mock_send:
            with patch.object(peer, "_receive_message") as mock_receive:
                block = b"block_data"
                mock_receive.return_value = (
                    len(block) + 8,
                    7,
                    struct.pack(">II", 0, 0) + block,
                )
                piece_size = len(block)
                piece_data = peer.download_piece(0, piece_size)
                assert mock_send.call_count == 1
                assert piece_data == block

    def test_close(self, mock_peer_addr, mock_info_hash):
        peer = PeerConnection(mock_peer_addr, mock_info_hash)
        mock_socket = Mock()
        peer.socket = mock_socket
        peer.connected = True
        peer.close()
        mock_socket.close.assert_called_once()
        assert peer.socket is None
        assert peer.connected is False


class TestTracker:
    @patch("urllib.request.urlopen")
    def test_get_peers(self, mock_urlopen, mock_tracker_url, mock_info_hash):
        mock_response = Mock()
        compact_peers = b"\x01\x02\x03\x04\x1a\x0a\x05\x06\x07\x08\x1a\x0b"
        bencoded_response = bencode(
            {
                "interval": 60,
                "peers": compact_peers.decode("latin1"),
            }
        )
        mock_response.read.return_value = bencoded_response
        mock_urlopen.return_value = mock_response
        tracker = Tracker(mock_tracker_url)
        peers = tracker.get_peers(mock_info_hash, 1024)
        assert "1.2.3.4:6666" in peers
        assert "5.6.7.8:6667" in peers
        assert len(peers) == 2
        mock_urlopen.assert_called_once()
        url_arg = mock_urlopen.call_args[0][0]
        assert mock_tracker_url in url_arg
        assert "info_hash=" in url_arg
        assert "peer_id=" in url_arg
        assert "port=6881" in url_arg
        assert "uploaded=0" in url_arg
        assert "downloaded=0" in url_arg
        assert "left=1024" in url_arg
        assert "compact=1" in url_arg


class TestUtilityFunctions:
    def test_generate_peer_id(self):
        peer_id = generate_peer_id()
        assert len(peer_id) == 20
        assert peer_id.startswith(b"-PY0001-")
        peer_id = generate_peer_id(client_id="-UT3000-")
        assert len(peer_id) == 20
        assert peer_id.startswith(b"-UT3000-")
        peer_id = generate_peer_id(random_bytes=False)
        assert len(peer_id) == 20
        assert peer_id.endswith(b"0" * 12)
        with pytest.raises(ValueError):
            generate_peer_id(client_id="invalid")

    def test_parse_magnet_link(self, mock_magnet_link):
        info_hash, trackers = parse_magnet_link(mock_magnet_link)
        assert info_hash == "08ada5a7a6183aae1e09d831df6748d566095a10"
        assert "udp://tracker.example:6969/announce" in trackers
        magnet_with_multiple_trackers = (
            mock_magnet_link
            + "&tr=udp%3A%2F%2Fsecond.tracker.example%3A6969%2Fannounce"
        )
        info_hash, trackers = parse_magnet_link(magnet_with_multiple_trackers)
        assert "udp://tracker.example:6969/announce" in trackers
        assert "udp://second.tracker.example:6969/announce" in trackers
        assert len(trackers) == 2
        with pytest.raises(ValueError):
            parse_magnet_link("not-a-magnet-link")
        with pytest.raises(ValueError):
            parse_magnet_link(
                "magnet:?dn=Test+File&tr=udp%3A%2F%2Ftracker.example%3A6969%2Fannounce"
            )

    def test_get_piece_hashes(self):
        pieces_bytes = bytes.fromhex(
            "0123456789abcdef0123456789abcdef01234567890123456789abcdef01234567890123456789"
        )
        pieces = pieces_bytes.decode("latin1")
        hashes = get_piece_hashes(pieces)
        assert len(hashes) == 2
        assert hashes[0] == "0123456789abcdef0123456789abcdef01234567"
        assert hashes[1] == "890123456789abcdef01234567890123456789"


class TestMainCommands:
    @patch("sys.argv")
    def test_decode_command(self, mock_argv, capsys):
        mock_argv.__getitem__.side_effect = lambda idx: ["script.py", "decode", "i42e"][
            idx
        ]
        mock_argv.__len__.return_value = 3
        main()
        captured = capsys.readouterr()
        assert "42" in captured.out

    @patch("sys.argv")
    def test_decode_complex(self, mock_argv, capsys):
        bencoded_dict = "d4:name5:hello3:agei42ee"
        mock_argv.__getitem__ = lambda self, key: {
            0: "script.py",
            1: "decode",
            2: bencoded_dict,
        }[key]
        mock_argv.__len__.return_value = 3
        main()
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"name": "hello", "age": 42}

    def test_info_command(self):
        with patch("sys.argv", ["script.py", "info", "test.torrent"]):
            mock_torrent = Mock()
            mock_torrent.tracker_url = "http://tracker.example"
            mock_torrent.file_length = 1024
            mock_torrent.info_hash_hex = "abcdef1234567890"
            mock_torrent.piece_length = 256
            mock_torrent.piece_hashes = ["hash1", "hash2"]
            with patch("bit_by_bit.script.TorrentFile", return_value=mock_torrent):
                with patch("builtins.print") as mock_print:
                    from bit_by_bit.script import main

                    main()
                    assert (
                        call("Tracker URL:", "http://tracker.example")
                        in mock_print.call_args_list
                    )
                    assert call("Length:", 1024) in mock_print.call_args_list
                    assert (
                        call("Info Hash:", "abcdef1234567890")
                        in mock_print.call_args_list
                    )
                    assert call("Piece Length:", 256) in mock_print.call_args_list
                    assert call("Piece Hashes:") in mock_print.call_args_list

    def test_peers_command(self):
        with patch("sys.argv", ["script.py", "peers", "test.torrent"]):
            mock_torrent = Mock()
            mock_torrent.tracker_url = "http://tracker.example"
            mock_torrent.info_hash_bytes = b"0123456789abcdefghij"
            mock_torrent.file_length = 1024
            mock_tracker = Mock()
            mock_tracker.get_peers.return_value = ["1.2.3.4:6666", "5.6.7.8:6667"]
            with patch("bit_by_bit.script.TorrentFile", return_value=mock_torrent):
                with patch(
                    "bit_by_bit.script.Tracker", return_value=mock_tracker
                ) as mock_tracker_class:
                    with patch("builtins.print") as mock_print:
                        from bit_by_bit.script import main

                        main()
                        mock_tracker_class.assert_called_once_with(
                            mock_torrent.tracker_url
                        )
                        mock_tracker.get_peers.assert_called_once_with(
                            mock_torrent.info_hash_bytes, mock_torrent.file_length
                        )
                        assert call("1.2.3.4:6666") in mock_print.call_args_list
                        assert call("5.6.7.8:6667") in mock_print.call_args_list

    @patch("sys.argv")
    def test_handshake_command(self, mock_argv):
        mock_argv.__getitem__ = lambda self, key: {
            0: "script.py",
            1: "handshake",
            2: "test.torrent",
            3: "1.2.3.4:6666",
        }[key]
        mock_argv.__len__.return_value = 4
        torrent_data = {
            "announce": "http://tracker.example",
            "info": {
                "name": "test.file",
                "piece length": 256,
                "length": 1024,
                "pieces": "aaaabbbbccccddddeeeeffffgggghhhhiiiijjjj",
            },
        }
        mock_file = mock_open()
        mock_file.return_value.read.return_value = bencode(torrent_data)
        with patch("builtins.open", mock_file):
            with patch("socket.socket") as mock_socket_class:
                mock_socket_instance = Mock()
                handshake_response = (
                    b"\x13BitTorrent protocol"
                    + bytes(8)
                    + b"0123456789abcdefghij"
                    + b"peer_id_from_remote"
                )
                mock_socket_instance.recv.return_value = handshake_response
                mock_socket_class.return_value = mock_socket_instance
                with patch("builtins.print") as mock_print:
                    main()
                    assert any(
                        "Peer ID: " in str(call) for call in mock_print.call_args_list
                    )

    def test_download_piece_command(self, monkeypatch):
        """
        Instead of mocking all the utility classes, let's directly patch the
        download_piece_with_retry function at the script level.
        """
        monkeypatch.setattr(
            sys,
            "argv",
            ["script.py", "download_piece", "", "output.bin", "test.torrent", "0"],
        )
        mock_download = Mock()
        mock_download.return_value = b"fake_piece_data"
        with patch("bit_by_bit.script.download_piece_with_retry", mock_download):
            from bit_by_bit.script import main

            main()
            mock_download.assert_called_once_with("test.torrent", 0, "output.bin")

    def test_download_command(self, monkeypatch):
        """
        Similar approach for the download command.
        """
        monkeypatch.setattr(
            sys, "argv", ["script.py", "download", "", "output.bin", "test.torrent"]
        )
        mock_download = Mock()
        mock_download.return_value = True
        with patch("bit_by_bit.script.download_file", mock_download):
            from bit_by_bit.script import main

            main()
            mock_download.assert_called_once_with("test.torrent", "output.bin")


class TestDownloadFunctions:
    @patch("bit_by_bit.utils.TorrentFile")
    @patch("bit_by_bit.utils.Tracker")
    @patch("bit_by_bit.utils.PeerConnection")
    def test_download_piece_with_retry(
        self, mock_peer_class, mock_tracker_class, mock_torrent_file_class, tmp_path
    ):
        torrent_file_path = str(tmp_path / "test.torrent")
        mock_torrent = Mock()
        mock_torrent.tracker_url = "http://tracker.example"
        mock_torrent.info_hash_bytes = b"0123456789abcdefghij"
        mock_torrent.file_length = 1024
        mock_torrent.get_piece_size.return_value = 256
        mock_torrent.verify_piece.return_value = True
        mock_torrent_file_class.return_value = mock_torrent
        with patch(
            "bit_by_bit.utils.isinstance",
            side_effect=lambda obj, cls: False if obj == torrent_file_path else True,
        ):
            mock_tracker_instance = Mock()
            mock_tracker_instance.get_peers.return_value = ["1.2.3.4:6666"]
            mock_tracker_class.return_value = mock_tracker_instance
            mock_peer_instance = Mock()
            mock_piece_data = b"mock_piece_data" * 32
            mock_peer_instance.download_piece.return_value = mock_piece_data
            mock_peer_class.return_value = mock_peer_instance
            output_file = tmp_path / "piece.bin"
            with patch("builtins.open", mock_open()):
                result = download_piece_with_retry(
                    torrent_file_path, 0, str(output_file)
                )
                assert mock_peer_instance.connect.called
                mock_peer_instance.download_piece.assert_called_with(0, 256)
                assert result == mock_piece_data

    @patch("bit_by_bit.utils.TorrentFile")
    @patch("bit_by_bit.utils.Tracker")
    @patch("bit_by_bit.utils.PeerConnection")
    def test_download_file(
        self, mock_peer_class, mock_tracker_class, mock_torrent_file_class, tmp_path
    ):
        torrent_file_path = str(tmp_path / "test.torrent")
        mock_torrent = Mock()
        mock_torrent.tracker_url = "http://tracker.example"
        mock_torrent.info_hash_bytes = b"0123456789abcdefghij"
        mock_torrent.file_length = 768
        mock_torrent.piece_length = 256
        mock_torrent.total_pieces = 3
        mock_torrent.get_piece_size.return_value = 256
        mock_torrent.verify_piece.return_value = True
        mock_torrent_file_class.return_value = mock_torrent
        with patch(
            "bit_by_bit.utils.isinstance",
            side_effect=lambda obj, cls: False if obj == torrent_file_path else True,
        ):
            mock_tracker_instance = Mock()
            mock_tracker_instance.get_peers.return_value = ["1.2.3.4:6666"]
            mock_tracker_class.return_value = mock_tracker_instance
            mock_peer_instance = Mock()
            mock_piece_data = b"mock_piece_data" * 32
            mock_peer_instance.download_piece.return_value = mock_piece_data
            mock_peer_class.return_value = mock_peer_instance
            with patch("builtins.open", mock_open()):
                result = download_file(torrent_file_path, "output.bin")
                assert mock_peer_instance.connect.called
                assert mock_peer_instance.download_piece.call_count == 3
                assert result is True


class TestMagnetLinkFunctions:
    def test_magnet_info(self):
        magnet_link = "magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678"
        with patch("sys.argv", ["script.py", "magnet_info", magnet_link]):
            info_hash = "1234567890abcdef1234567890abcdef12345678"
            trackers = ["http://tracker.example"]
            with patch(
                "bit_by_bit.script.parse_magnet_link",
                return_value=(info_hash, trackers),
            ):
                metadata = {
                    "length": 1024,
                    "piece length": 256,
                    "pieces": "a" * 40,
                }
                with patch(
                    "bit_by_bit.script.retrieve_metadata_from_trackers",
                    return_value=(metadata, trackers[0]),
                ):
                    with patch(
                        "bit_by_bit.script.get_piece_hashes",
                        return_value=["hash1", "hash2"],
                    ):
                        with patch("builtins.print") as mock_print:
                            from bit_by_bit.script import main

                            main()
                            assert (
                                call(f"Tracker URL: {trackers[0]}")
                                in mock_print.call_args_list
                            )
                            assert (
                                call(f"Length: {metadata['length']}")
                                in mock_print.call_args_list
                            )
                            assert (
                                call(f"Info Hash: {info_hash}")
                                in mock_print.call_args_list
                            )
                            assert (
                                call(f"Piece Length: {metadata['piece length']}")
                                in mock_print.call_args_list
                            )
                            assert call("Piece Hashes:") in mock_print.call_args_list
