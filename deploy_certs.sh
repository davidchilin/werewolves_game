#!/bin/bash

# Check if both arguments are provided
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Error: Missing arguments."
    echo "Usage: $0 <my_user> <my_site>"
    exit 1
fi

# Configuration using arguments
TARGET_USER="$1"
TARGET_GROUP="$1"
SITE_NAME="$2"

SOURCE_DIR="/etc/letsencrypt/live/$SITE_NAME"
TARGET_DIR="./ssl_certs"

# Create target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Verify source directory exists before copying
if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source directory $SOURCE_DIR does not exist."
    exit 1
fi

# Copy the standard certificate files
cp "$SOURCE_DIR/fullchain.pem" "$TARGET_DIR/"
cp "$SOURCE_DIR/privkey.pem" "$TARGET_DIR/"

# Adjust ownership and permissions
chown "$TARGET_USER:$TARGET_GROUP" "$TARGET_DIR"
chmod 700 "$TARGET_DIR"
chown "$TARGET_USER:$TARGET_GROUP" "$TARGET_DIR/fullchain.pem" "$TARGET_DIR/privkey.pem"
chmod 600 "$TARGET_DIR/privkey.pem"
chmod 644 "$TARGET_DIR/fullchain.pem"

echo "Certificates for $SITE_NAME successfully copied for user $TARGET_USER to $TARGET_DIR"
