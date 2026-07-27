"""Simple HTTP server that redirects aelflab.com → hub.aelflab.com"""
from http.server import HTTPServer, BaseHTTPRequestHandler

class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(301)
        self.send_header("Location", "https://hub.aelflab.com" + self.path)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8082), RedirectHandler)
    print("Redirect server running on :8082 → hub.aelflab.com")
    server.serve_forever()
