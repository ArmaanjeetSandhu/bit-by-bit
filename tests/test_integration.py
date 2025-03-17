import os

import pytest

from bit_by_bit.utils import (
    TorrentFile,
    download_piece_with_retry,
    parse_magnet_link,
    retrieve_metadata_from_trackers,
)


@pytest.mark.integration
class TestRealTorrentFile:
    """Tests that use a real torrent file."""

    def test_parse_real_torrent(self, real_torrent_file):
        """Test that we can parse a real torrent file."""
        torrent = TorrentFile(real_torrent_file)
        assert torrent.tracker_url
        assert torrent.piece_length > 0
        assert torrent.file_length > 0
        assert len(torrent.piece_hashes) > 0
        assert torrent.info_hash_hex
        print("\nReal torrent info:")
        print(f"Tracker URL: {torrent.tracker_url}")
        print(f"Length: {torrent.file_length} bytes")
        print(f"Piece Length: {torrent.piece_length} bytes")
        print(f"Total Pieces: {torrent.total_pieces}")
        print(f"Info Hash: {torrent.info_hash_hex}")


@pytest.mark.integration
@pytest.mark.slow
class TestRealDownloads:
    """Tests that perform real downloads from the BitTorrent network."""

    def test_download_single_piece(self, real_torrent_file, tmp_path):
        """Test downloading a single piece from a real torrent."""
        output_file = tmp_path / "piece_0.bin"
        piece_data = download_piece_with_retry(real_torrent_file, 0, str(output_file))
        assert piece_data is not None
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0
        with open(output_file, "rb") as f:
            file_data = f.read()
            assert file_data == piece_data
        print(f"\nSuccessfully downloaded piece 0 ({len(piece_data)} bytes)")


@pytest.mark.integration
class TestRealMagnetLink:
    """Tests that use a real magnet link."""

    def test_parse_real_magnet(self, real_magnet_link):
        """Test that we can parse a real magnet link."""
        info_hash, trackers = parse_magnet_link(real_magnet_link)
        assert info_hash
        assert len(info_hash) == 40
        assert trackers
        print("\nReal magnet info:")
        print(f"Info Hash: {info_hash}")
        print(f"Trackers: {', '.join(trackers)}")

    @pytest.mark.slow
    def test_retrieve_metadata(self, real_magnet_link):
        """Test retrieving metadata from a real magnet link."""
        info_hash, trackers = parse_magnet_link(real_magnet_link)
        metadata, tracker_url = retrieve_metadata_from_trackers(info_hash, trackers)
        if metadata:
            assert "length" in metadata
            assert "piece length" in metadata
            assert "pieces" in metadata
            print(f"\nRetrieved metadata from {tracker_url}:")
            print(f"Length: {metadata['length']} bytes")
            print(f"Piece Length: {metadata['piece length']} bytes")
            print(f"Pieces: {len(metadata['pieces']) // 20} total")
        else:
            pytest.skip("Could not retrieve metadata from any tracker")
