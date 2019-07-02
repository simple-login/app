"""
ssh-keygen -t rsa -b 4096 -m PEM -f jwtRS256.key
# Don't add passphrase
openssl rsa -in jwtRS256.key -pubout -outform PEM -out jwtRS256.key.pub

"""
from jwcrypto import jwk, jws, jwt

with open("jwtRS256.key", "rb") as f:
    key = jwk.JWK.from_pem(f.read())

Token = jwt.JWT(header={"alg": "RS256"}, claims={"info": "I'm a signed token"})
Token.make_signed_token(key)
print(Token.serialize())

# verify
jwt.JWT(key=key, jwt=Token.serialize())
