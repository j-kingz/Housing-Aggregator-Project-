import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug mode reloads the code on every change, which is handy while you are
    # working locally but must stay off in the container
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=debug,
    )
