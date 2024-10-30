from flask_webgoat import create_app

app = create_app()

@app.after_request
def add_csp_headers(response):
    # vulnerability: Broken Access Control
    response.headers['Access-Control-Allow-Origin'] = '*'
    # vulnerability: Security Misconfiguration
    response.headers['Content-Security-Policy'] = "script-src 'self' 'unsafe-inline'"
    return response

if __name__ == '__main__':
    # vulnerability: Security Misconfiguration
    app.run(debug=True)
