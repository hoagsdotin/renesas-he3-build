import sys
import re
import os

def parse_srec_file(input_file):
    """Parses the .mot (S-record) file, extracts data bytes, removes the last checksum byte, and fills missing addresses with 0xFF."""
    formatted_lines = []
    addresses = []
    data_map = {}
    srec_map = {}

    with open(input_file, "r") as f:
        for line in f:
            if line.startswith(("S1", "S2", "S3")):
                byte_count = int(line[2:4], 16)  # Byte count from the S-record
                address_bytes = 4 if line.startswith("S1") else 6 if line.startswith("S2") else 8
                data_start = 4 + address_bytes  # Data starts after byte count & address
                data_end = -2  # Ignore checksum (last byte)

                address = int(line[4:4+address_bytes], 16)  # Extract address
                data = line[data_start:data_end]  # Extract data bytes excluding checksum

                # Convert data to bytes, ensuring only the last byte (checksum) is removed
                data_bytes = [f"0x{data[i:i+2]}" for i in range(0, len(data)-2, 2)] if len(data) >= 2 else []

                addresses.append(address)
                data_map[address] = data_bytes
                srec_map[address] = line.strip()  # Store original S-record

    addresses.sort()

    previous_address = None
    for addr in addresses:
        if previous_address is not None:
            expected_next_address = previous_address + len(data_map[previous_address])
            if addr > expected_next_address:
                missing_bytes = addr - expected_next_address
                formatted_lines.append(f"    // {missing_bytes} Bytes missing")
                formatted_lines.append("    " + ", ".join(["0xFF"] * missing_bytes) + ",")

        # Add S-record comment
        formatted_lines.append(f"    // {srec_map[addr]}")
        formatted_lines.append("    " + ", ".join(data_map[addr]) + ",")
        
        previous_address = addr

    return formatted_lines

def read_version(version_file, build_type):
    """Reads major and minor version from Version.h based on build type."""
    build_map = {"dev": "DEV", "test": "TEST", "mp": "MP"}
    selected_build = build_map.get(build_type.lower(), "DEV")

    major_version, minor_version = None, None

    with open(version_file, "r") as f:
        for line in f:
            major_match = re.match(rf"#define VERSION_MAJOR_{selected_build} (\d+)", line)
            minor_match = re.match(rf"#define VERSION_MINOR_{selected_build} (\d+)", line)

            if major_match:
                major_version = major_match.group(1)
            if minor_match:
                minor_version = minor_match.group(1)

            if major_version is not None and minor_version is not None:
                break

    if major_version is None or minor_version is None:
        raise ValueError(f"Version information for {selected_build} not found in {version_file}")

    return major_version, minor_version

def write_output_header(hex_data, major, minor, output_file):
    """Writes the extracted hex data into a .h file with proper format."""
    
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(output_file, "w") as f:
        f.write("#ifndef RENESAS_FIRMWARE_H_\n#define RENESAS_FIRMWARE_H_\n\n")
        f.write(f"#define FIRMWARE_VERSION_MAJOR {major}\n")
        f.write(f"#define FIRMWARE_VERSION_MINOR {minor}\n\n")
        f.write("const unsigned char firmware_data[] = {\n")

        for line in hex_data:
            f.write(line + "\n")

        f.write("};\n\n")
        f.write("#define FIRMWARE_SIZE (sizeof(firmware_data) / sizeof(firmware_data[0]))\n")
        f.write("#endif /* RENESAS_FIRMWARE_H_ */\n")

    print(f"Conversion complete! Output saved to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python convert_firmware.py <input.mot> <output_path/output.h> <version.h> <build_type>")
        sys.exit(1)

    input_mot = sys.argv[1]
    output_h = sys.argv[2]
    version_h = sys.argv[3]
    build_type = sys.argv[4]

    try:
        firmware_data = parse_srec_file(input_mot)
        major, minor = read_version(version_h, build_type)
        write_output_header(firmware_data, major, minor, output_h)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
