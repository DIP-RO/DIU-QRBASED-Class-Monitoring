from backend.auth import safe_return_path

def test_return_path_rejects_external_redirects():
    assert safe_return_path("/q/token")=="/q/token"
    assert safe_return_path("//evil.example/path")=="/"
    assert safe_return_path("https://evil.example")=="/"
