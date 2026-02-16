"""Run admin server directly with: python -m xspider.admin"""

import uvicorn


def main():
    """Start the admin server."""
    print("Starting xspider admin server...")
    print()
    print("Admin panel: http://localhost:8000/admin/dashboard")
    print("API docs: http://localhost:8000/api/docs")
    print()
    print("Default admin credentials: admin / admin123")
    print()

    uvicorn.run(
        "xspider.admin.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
