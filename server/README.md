# AFT Server

Flask-based REST API server for the AFT (Aim, Focus, Track) application.

## Architecture

The server is built with:
- **Flask**: Web framework
- **SQLAlchemy**: ORM for database operations
- **Alembic**: Database migrations
- **MySQL**: Database backend
- **Swagger/Flasgger**: API documentation

## Project Structure

```
server/
├── app.py                    # Flask app bootstrap, middleware, scheduler init
├── *_routes.py               # Route modules grouped by domain
├── auth.py                   # Authentication/session routes
├── websocket_handlers.py     # Socket.IO event handlers and auth checks
├── database.py               # Database configuration and session management
├── models.py                 # SQLAlchemy models (boards, cards, users, roles, etc.)
├── utils.py                  # Validation and utility functions
├── *_scheduler.py            # Backup/card/housekeeping background schedulers
├── scheduler_lock.py         # Startup lock to avoid duplicate scheduler init
├── migrate.py                # Migration management script
├── alembic/                  # Database migration files
├── tests/                    # Test suite
│   ├── test_utils.py         # Unit tests for utilities
│   ├── test_api_*.py         # API integration tests
│   └── test_api_edge_cases.py # Security and edge case tests
├── requirements.txt          # Production dependencies
├── requirements-dev.txt      # Development/testing dependencies
└── docs/                     # Server documentation
   └── SERVER_TESTING.md      # Testing documentation
```

## Key Features

### Security

The API implements multiple security layers:

1. **Input Validation**:
   - All user inputs are validated for type, length, and format
   - String inputs are sanitized (whitespace trimming)
   - Integer inputs are validated for range (non-negative for order/ID fields)
   - Maximum length limits enforced (255 chars for names, 2000 for descriptions)

2. **Request Protection**:
   - Request size limit (10MB) to prevent DoS attacks
   - Content-Type validation for JSON endpoints
   - Proper HTTP status codes for all error conditions

3. **SQL Injection Protection**:
   - SQLAlchemy ORM with parameterized queries
   - No raw SQL with user input

4. **Error Handling**:
   - Standardized error responses
   - Errors logged but sensitive details not exposed to clients
   - Database rollback on errors

### Input Validation

The `utils.py` module provides comprehensive validation:

- `validate_string_length()` - Validates string length with configurable max
- `validate_integer()` - Validates integers with optional min/max constraints
- `sanitize_string()` - Sanitizes string input (trims whitespace)
- `create_error_response()` - Creates standardized error responses
- `create_success_response()` - Creates standardized success responses

### Data Model Coverage

The data model extends beyond boards/cards/settings and includes authentication, role/permission, scheduling, notification, and collaboration entities.

See `models.py` and `server/docs/PERMISSION_MODEL.md` for the authoritative model and permission details.

## API Surface (Overview)

Core API groups include:
- Authentication/session and user approval
- User and role/permission management
- Boards, columns, cards, comments, checklist items, timestamps
- Scheduling and recurring card automation
- Notifications and housekeeping health
- Themes and application settings
- Backup/restore and database operational endpoints
- Health, version, stats, and API docs (`/api/docs`)

Use Swagger at `/api/docs` for the current endpoint contract.

## Development

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For testing/linting
```

2. Configure environment variables:

Copy the `.env.example` file to `.env` and update it with your configuration:
```bash
cp .env.example .env
# Edit .env with your settings
```

Or set environment variables directly:
```bash
export MYSQL_USER=your_user
export MYSQL_PASSWORD=your_password
export MYSQL_DATABASE=aft
```

3. Run migrations:
```bash
alembic upgrade head
```

4. Start the server:
```bash
python app.py
# Or with gunicorn:
gunicorn --config gunicorn.conf.py app:app  # reads GUNICORN_WORKERS / GUNICORN_THREADS
```

### Testing

See [SERVER_TESTING.md](docs/SERVER_TESTING.md) for comprehensive testing documentation.

Quick start:
```bash
# Run unit tests (fast, no API required)
pytest -m unit

# Run all tests (requires Docker containers running)
pytest
```

### Code Quality

The project uses:
- **Black**: Code formatting (`black app.py utils.py`)
- **Pylint**: Static analysis (`pylint app.py utils.py`)
- **MyPy**: Type checking (`mypy app.py utils.py`)

Apply formatting:
```bash
black server/
```

### Migrations

Create a new migration:
```bash
python migrate.py create "description of changes"
```

Apply migrations:
```bash
python migrate.py upgrade
```

Rollback a migration:
```bash
python migrate.py downgrade
```

## Security Considerations

### Implemented Protections

✅ **Input Validation**: All user inputs validated for type, length, and format
✅ **SQL Injection**: Protected by SQLAlchemy parameterized queries
✅ **DoS Protection**: Request size limits (10MB)
✅ **Type Safety**: Strict type checking (e.g., rejects boolean where int expected)
✅ **Length Limits**: Enforced on all string fields
✅ **Error Handling**: Safe error messages, no sensitive data leakage
✅ **Content-Type Validation**: Ensures proper JSON format

### Recommended Additional Protections

⚠️ **Rate Limiting**: Consider adding rate limiting for production (e.g., Flask-Limiter)
⚠️ **HTTPS**: Always use HTTPS in production
⚠️ **CORS**: Configure CORS policies for your domain
⚠️ **CSRF Protection**: Add CSRF tokens if using session-based auth

### Security Testing

The test suite includes comprehensive security tests:
- SQL injection attempts
- XSS payload storage (frontend must escape on display)
- Oversized input handling
- Type confusion attacks
- Invalid data type handling
- Concurrent operation race conditions

All security tests are in `tests/test_api_edge_cases.py`.

## Environment Variables

Required:
- `MYSQL_USER` - Database username
- `MYSQL_PASSWORD` - Database password
- `MYSQL_DATABASE` - Database name

Optional:
- `FLASK_ENV` - Set to "development" for debug mode
- `LOG_LEVEL` - Logging level (default: INFO)

### Managing Environment Variables

The `.env.example` file contains all available configuration options with default values. When upgrading or pulling new changes:

1. **On upgrade/pull**: Always review the `.env.example` file for new variables
2. **Update your `.env`**: Add any new variables that don't exist in your current `.env` file
3. **Keep your values**: Preserve your existing configuration values while adding new keys

This ensures you have all required configuration options and won't miss new features or security-critical settings.

## Deployment

The server is designed to run in Docker. See the root `compose.yml` for the complete setup.

Key considerations:
- Use environment variables for all configuration
- Run database migrations on startup
- Use Gunicorn for production (not Flask dev server)
- Configure proper logging
- Set up database backups
- Monitor disk space for database growth

## API Documentation

Interactive API documentation is available at `/api/docs` when the server is running. This is powered by Swagger/Flasgger and provides:
- Complete API reference
- Request/response examples
- Try-it-out functionality
- Schema definitions

## License

See LICENSE file in the root directory.
