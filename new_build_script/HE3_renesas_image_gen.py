#!/usr/bin/env python3
import os
import sys
import struct
import xml.etree.ElementTree as ET

# ------------------------------ CONFIGURATION ------------------------------

# Base and input paths
_script_dir = os.path.dirname(os.path.abspath(__file__))
_sdk_root = os.path.join(_script_dir, "HE3", "sdk-ameba-v7.1d")
base_path = os.path.join(_sdk_root, "project", "realtek_amebaz2_v0_example", "GCC-RELEASE", "application_is", "Debug", "bin")
external_path = os.path.join(_sdk_root, "Hoags")

flash_is_path = os.path.join(base_path, 'flash_is.bin')
firmware_is_path = os.path.join(base_path, 'firmware_is.bin')

# Renesas and XML from external path
reneses_path = os.path.join(external_path, 'reneses.bin')
metadata_xml = os.path.join(external_path, 'metadata.xml')

# Skip gracefully if files are missing for non-Renesas targets
if not os.path.exists(reneses_path) or not os.path.exists(metadata_xml):
    print(f"[SKIP] {reneses_path} or {metadata_xml} not found. Skipping Renesas image generation.")
    sys.exit(0)

if not os.path.exists(flash_is_path) or not os.path.exists(firmware_is_path):
    print(f"[SKIP] Base binaries not found in {base_path}. Skipping Renesas image generation.")
    sys.exit(0)

# Output directory
output_dir = os.path.join(base_path, 'Flash and OTA files')
os.makedirs(output_dir, exist_ok=True)

# Output filenames in the output directory
flash_output = os.path.join(output_dir, 'HE3_renesas_flash_is.bin')
ota_output = os.path.join(output_dir, 'HE3_renesas_firmware_is.bin')
final_output = os.path.join(output_dir, 'OTA_final_he3_renesas.bin')

# Size constants
FLASH_IMAGE1_MAX_SIZE = 1364 * 1024  # flash_is + bootloader
FLASH_IMAGE2_MAX_SIZE = 508 * 1024  # reneses

OTA_IMAGE1_MAX_SIZE = 1300 * 1024    # firmware_is
OTA_IMAGE2_MAX_SIZE = 507 * 1024    # reneses

# ------------------------------ COMMON UTILS ------------------------------

def pad_with_ff(data: bytes, final_size: int) -> bytes:
    if len(data) > final_size:
        raise ValueError(f"Data size ({len(data)} bytes) exceeds allowed limit ({final_size} bytes)")
    return data + b'\xFF' * (final_size - len(data))

def pad_to_32bit(data: bytes) -> bytes:
    pad_len = (4 - (len(data) % 4)) % 4
    return data + b'\x00' * pad_len

def compute_checksum(data: bytes) -> int:
    data = pad_to_32bit(data)
    checksum = 0
    for i in range(0, len(data), 4):
        word, = struct.unpack('>I', data[i:i+4])
        checksum = (checksum + word) & 0xFFFFFFFF
    return (-checksum) & 0xFFFFFFFF

# ------------------------------ STAGE 1: FLASH IMAGE ------------------------------

def create_flash_image():
    with open(flash_is_path, 'rb') as f:
        img1 = f.read()
    with open(reneses_path, 'rb') as f:
        img2 = f.read()

    print(f"[FLASH] Image 1 size: {len(img1)} bytes")
    print(f"[FLASH] Image 2 size: {len(img2)} bytes")

    padded_img1 = pad_with_ff(img1, FLASH_IMAGE1_MAX_SIZE)
    padded_img2 = pad_with_ff(img2, FLASH_IMAGE2_MAX_SIZE)

    with open(flash_output, 'wb') as out:
        out.write(padded_img1 + padded_img2)

    print(f"[FLASH] Combined image saved as '{flash_output}' ({len(padded_img1) + len(padded_img2)} bytes)")

# ------------------------------ STAGE 2: OTA IMAGE ------------------------------

def create_ota_image():
    with open(firmware_is_path, 'rb') as f:
        img1 = f.read()
    with open(reneses_path, 'rb') as f:
        img2 = f.read()

    print(f"[OTA] Image 1 size: {len(img1)} bytes")
    print(f"[OTA] Image 2 size: {len(img2)} bytes")

    padded_img1 = pad_with_ff(img1, OTA_IMAGE1_MAX_SIZE)
    padded_img2 = pad_with_ff(img2, OTA_IMAGE2_MAX_SIZE)

    with open(ota_output, 'wb') as out:
        out.write(padded_img1 + padded_img2)

    print(f"[OTA] Combined image saved as '{ota_output}' ({len(padded_img1) + len(padded_img2)} bytes)")

# ------------------------------ STAGE 3: FINAL IMAGE ------------------------------

def parse_metadata(xml_file: str) -> list:
    tree = ET.parse(xml_file)
    root = tree.getroot()
    tag_value_list = []

    for tag in root.findall('tag'):
        tagname = tag.find('tagname').text.strip()
        tagno = int(tag.find('tagno').text.strip())
        value = tag.find('value').text.strip().encode('utf-8')
        print(f"[META] Parsed Tag - Name: {tagname}, Tag No: {tagno}, Value: {value}")
        tag_value_list.append((tagno, value))

    return tag_value_list

def build_tlv_block(tag_value_list: list) -> bytes:
    tlv_data = b''
    for tagno, value in tag_value_list:
        tag_bytes = struct.pack('>I', tagno)
        length_bytes = struct.pack('>I', len(value))
        tlv_entry = tag_bytes + length_bytes + value
        tlv_data += pad_to_32bit(tlv_entry)
    return tlv_data

def create_final_image():
    with open(ota_output, 'rb') as f:
        firmware_data = pad_to_32bit(f.read())

    tag_value_list = parse_metadata(metadata_xml)
    tlv_block = build_tlv_block(tag_value_list)

    offset_length = len(firmware_data)
    offset_bytes = struct.pack('>I', offset_length)

    final_data = firmware_data + tlv_block + offset_bytes

    checksum = compute_checksum(final_data)
    checksum_bytes = struct.pack('>I', checksum)
    final_data += checksum_bytes

    print(f"[FINAL] TLV starts at offset: {offset_length} bytes")
    print(f"[FINAL] Checksum: 0x{checksum:08X}")
    print(f"[FINAL] Checksum valid: {compute_checksum(final_data) == 0}")

    with open(final_output, 'wb') as f:
        f.write(final_data)

    print(f"[FINAL] Final firmware written to: {final_output}")

# ------------------------------ MAIN ENTRY POINT ------------------------------

if __name__ == '__main__':
    print("\n=== Step 1: Creating FLASH image ===")
    create_flash_image()

    print("\n=== Step 2: Creating OTA image ===")
    create_ota_image()

    print("\n=== Step 3: Creating FINAL image with metadata and checksum ===")
    create_final_image()
