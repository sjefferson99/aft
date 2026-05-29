"""Branding routes for instance-wide logo management."""

import logging
import os
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from database import SessionLocal
from models import InstanceConfig
from utils import create_error_response, create_success_response, require_permission

logger = logging.getLogger(__name__)

branding_bp = Blueprint("branding_routes", __name__)

ALLOWED_LOGO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
MAX_LOGO_UPLOAD_BYTES = 100 * 1024  # 100KB
CUSTOM_LOGO_CONFIG_KEY = 'custom_logo_filename'
LOGOS_DIR = Path('/var/www/images/backgrounds/logos')


@branding_bp.route('/api/branding/logo', methods=['GET'])
def get_branding_logo():
    """Get the active instance logo filename.
    ---
    tags:
      - Branding
    responses:
      200:
        description: Active logo filename (or null when default logo is active)
        schema:
          type: object
          properties:
            filename:
              type: string
              nullable: true
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        return jsonify({'filename': config.value if config and config.value else None}), 200
    except Exception as e:
        logger.error(f"Error getting branding logo: {str(e)}")
        return create_error_response('Error getting branding logo', 500)
    finally:
        session.close()


@branding_bp.route('/api/branding/logo', methods=['POST'])
@require_permission('branding.edit')
def upload_branding_logo():
    """Upload a new instance-wide logo.
    ---
    tags:
      - Branding
    security:
      - session: []
    consumes:
      - multipart/form-data
    parameters:
      - name: image
        in: formData
        required: true
        type: file
        description: Logo image file (recommended WebP/PNG, max 100KB)
    responses:
      200:
        description: Uploaded logo filename
        schema:
          type: object
          properties:
            filename:
              type: string
      400:
        description: Missing file, invalid type, or size limit exceeded
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        if 'image' not in request.files:
            return create_error_response('No image file provided', 400)

        file = request.files['image']
        if file.filename == '':
            return create_error_response('No file selected', 400)

        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in ALLOWED_LOGO_EXTENSIONS:
            allowed = ', '.join(sorted(ALLOWED_LOGO_EXTENSIONS))
            return create_error_response(f'Invalid file type. Allowed: {allowed}', 400)

        # Validate file size before saving to disk.
        file.stream.seek(0, os.SEEK_END)
        file_size = file.stream.tell()
        file.stream.seek(0)
        if file_size > MAX_LOGO_UPLOAD_BYTES:
            return create_error_response('File too large. Maximum allowed size is 100KB', 400)

        LOGOS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        filename = f'logo_{timestamp}_{unique_id}{file_ext}'
        file_path = LOGOS_DIR / filename
        file.save(str(file_path))

        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        if not config:
            config = InstanceConfig(key=CUSTOM_LOGO_CONFIG_KEY, value=filename)
            session.add(config)
        else:
            config.value = filename

        session.commit()
        return jsonify({'filename': filename}), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error uploading branding logo: {str(e)}")
        return create_error_response('Error uploading branding logo', 500)
    finally:
        session.close()


@branding_bp.route('/api/branding/logo', methods=['DELETE'])
@require_permission('branding.edit')
def clear_branding_logo():
    """Reset instance logo to the default built-in logo.
    ---
    tags:
      - Branding
    security:
      - session: []
    responses:
      200:
        description: Logo reset successfully
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        if config:
            session.delete(config)
            session.commit()

        return create_success_response(message='Custom logo reset to default')
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing branding logo: {str(e)}")
        return create_error_response('Error clearing branding logo', 500)
    finally:
        session.close()
