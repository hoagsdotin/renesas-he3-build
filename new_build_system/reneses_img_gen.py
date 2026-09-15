global PACKET_SIZE, NUM_PACKETS
PACKET_SIZE = 132  # 128 bytes data + 4 bytes header/checksum
NUM_PACKETS = 0

def srec_to_ascii_array(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()
    
    ascii_arrays = []
    
    for line in lines:
        line = line.strip()  # Remove newline or extra spaces
        ascii_bytes = bytes(line, 'ascii')  # Convert ASCII to bytes
        ascii_hex = " ".join(f"{byte:02X}" for byte in ascii_bytes)

        # Append 0x0D 0x0A (Carriage Return + Line Feed) after every complete line
        ascii_hex += " 0D 0A"

        ascii_arrays.append(ascii_hex)

    return ascii_arrays

def calculate_checksum(data):
    """Calculate 8-bit checksum for XMODEM protocol."""
    return sum(data) & 0xFF  # Sum all bytes and take the least significant byte

def add_xmodem_checksum(ascii_data):
    global NUM_PACKETS
    packets = []
    block_number = 1  # Start block number at 1

    # Convert ASCII hex string into raw bytes
    raw_data = b''.join(bytes.fromhex(line.replace(" ", "")) for line in ascii_data)

    # Split into 128-byte chunks for XMODEM
    for i in range(0, len(raw_data), 128):
        chunk = raw_data[i:i+128]
        
        # Pad with 0x1A if less than 128 bytes
        if len(chunk) < 128:
            chunk += b'\x1A' * (128 - len(chunk))  # Ensure correct padding

        # XMODEM Checksum Packet Structure
        packet = bytearray()
        packet.append(0x01)  # SOH (Start of Header)
        packet.append(block_number & 0xFF)  # Block Number
        packet.append(0xFF - (block_number & 0xFF))  # Block Number Complement
        packet.extend(chunk)  # Data (128 Bytes)

        # Compute and append 8-bit checksum
        checksum = calculate_checksum(chunk)
        packet.append(checksum)

        packets.append(packet)
        block_number += 1
    
    NUM_PACKETS = len(packets)
    return packets

def write_to_bin_file(packets, output_file):
    with open(output_file, "wb") as f:
        for packet in packets:
            f.write(packet)
    print(f"Wrote {len(packets)} packets to binary file: {output_file}")


def print_row_count(file_path, row_size=132):
    with open(file_path, 'rb') as f:
        data = f.read()

    total_bytes = len(data)
    row_count = (total_bytes + row_size - 1) // row_size  # Ceiling division

    print(f"Total bytes: {total_bytes}")
    print(f"Row size: {row_size} bytes")
    print(f"Number of rows: {row_count}")

# === Example usage ===
file_path = "output.srec"  # Input .srec file
output_bin_file = "reneses.bin"  # Output .bin file

ascii_data = srec_to_ascii_array(file_path)
xmodem_packet_array = add_xmodem_checksum(ascii_data)

# Write to .bin file
write_to_bin_file(xmodem_packet_array, output_bin_file)

print_row_count("reneses.bin", row_size=132)
