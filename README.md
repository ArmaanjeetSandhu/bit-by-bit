# Bit-By-Bit: The BitTorrent Client

This is a simple BitTorrent client implementation in Python. It allows users to decode and interact with torrent files, connect to peers, and download files using the BitTorrent protocol.

## Usage

The script provides two main functionalities: decoding Bencode and extracting torrent info.

### Decoding Bencode

To decode a Bencoded string:

```
python script.py decode "d3:cow3:moo4:spam4:eggse"
```

This will output the decoded data in JSON format:

```json
{ "cow": "moo", "spam": "eggs" }
```

### Extracting Torrent Info

To extract basic information from a torrent file:

```
python script.py info path/to/your/torrent/file.torrent
```

This will output the following details:

```
Tracker URL: http://tracker.example.com/announce
Length: 1048576
Info Hash: 5ab4f42c8b76f0f3fd738181bfb0c7cec5a9a93a
Piece Length: 16384
Piece Hashes:
8c5d25d6ccb7c36fa5a460b49cd1e8ef584a591a
f9c0a94b4a53edd465a2c891bcc0eab5f8a9e4a1
d4d2b5c7e8f1a3b6d9c0e2f5a8b1d4e7c9f3a6b2
1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0
7f1e3d5c9b8a0f2e4d6c8b0a2f4e6d8c0b2a4f6
3c5e7g9i1k3m5o7q9s1u3w5y7a9c1e3g5i7k9m
9n8m7l6k5j4i3h2g1f0e9d8c7b6a5z4y3x2w1v
2w4y6a8c0e2g4i6k8m0o2q4s6u8w0y2a4c6e8g
8h0j2l4n6p8r0t2v4x6z8b0d2f4h6j8l0n2p4r
4s6u8w0y2a4c6e8g0i2k4m6o8q0s2u4w6y8a0c
0d2f4h6j8l0n2p4r6t8v0x2z4b6d8f0h2j4l6n
6o8q0s2u4w6y8a0c2e4g6i8k0m2o4q6s8u0w2y
2z4b6d8f0h2j4l6n8p0r2t4v6x8z0b2d4f6h8j
8k0m2o4q6s8u0w2y4a6c8e0g2i4k6m8o0q2s4u
4v6x8z0b2d4f6h8j0l2n4p6r8t0v2x4z6b8d0f
0g2i4k6m8o0q2s4u6w8y0a2c4e6g8i0k2m4o6q
6r8t0v2x4z6b8d0f2h4j6l8n0p2r4t6v8x0z2b
2c4e6g8i0k2m4o6q8s0u2w4y6a8c0e2g4i6k8m
8n0p2r4t6v8x0z2b4d6f8h0j2l4n6p8r0t2v4x
4y6a8c0e2g4i6k8m0o2q4s6u8w0y2a4c6e8g0i
0j2l4n6p8r0t2v4x6z8b0d2f4h6j8l0n2p4r6t
6u8w0y2a4c6e8g0i2k4m6o8q0s2u4w6y8a0c2e
2f4h6j8l0n2p4r6t8v0x2z4b6d8f0h2j4l6n8p
8q0s2u4w6y8a0c2e4g6i8k0m2o4q6s8u0w2y4a
4b6c8d0e2f4g6h8i0j2k4l6m8n0p2q4r6s8t0u
```

## Note

This project was created as a learning exercise in understanding the BitTorrent protocol and implementing a basic client. It is not intended for production use and may not fully comply with all aspects of the BitTorrent specification.
