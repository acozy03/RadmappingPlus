from flask import redirect
from app import create_app

app = create_app()
@app.route('/')
def index():
    return redirect('/auth/login')

if __name__ == '__main__':
    app.run(debug=True)