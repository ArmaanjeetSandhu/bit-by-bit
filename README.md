# Bit-By-Bit: The BitTorrent Client

This is a simple BitTorrent client implementation in Python. It allows users to decode and interact with torrent files, connect to peers, and download files using the BitTorrent protocol.

## Usage

The script provides two main functionalities: decoding Bencode and extracting torrent info.

### Decoding Bencode

To decode a Bencode-encoded string:

```
python bencode_decoder.py decode "d3:cow3:moo4:spam4:eggse"
```

This will output the decoded data in JSON format:

```json
{ "cow": "moo", "spam": "eggs" }
```

### Extracting Torrent Info

To extract basic information from a torrent file:

```
python bencode_decoder.py info path/to/your/torrent/file.torrent
```

This will output the tracker URL and the total length of the file(s) in the torrent:

```
Tracker URL: http://bttracker.debian.org:6969/announce
Length: 351272960
```

## Note

This project was created as a learning exercise in understanding the BitTorrent protocol and implementing a basic client. It is not intended for production use and may not fully comply with all aspects of the BitTorrent specification.
