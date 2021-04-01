## OAuth

SL currently supports code and implicit flow.

#### Code flow

To trigger the code flow locally, you can go to the [following url](http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=random_string) after running `python server.py`:


You should see the authorization page where user is asked for permission to share their data. Once user approves, user is redirected to this url with an `authorization code`: `http://localhost:7000/callback?state=123456&code=the_code`

Next, exchange the code to get the token with `{code}` replaced by the code obtained in previous step. The `http` tool used here is [httpie](https://httpie.org)

```
http -f -a client-id:client-secret http://localhost:7777/oauth/token grant_type=authorization_code code={code}
```

This should return an `access token` that allows to get user info via the following command. Again, `http` is used.

```
http http://localhost:7777/oauth/user_info 'Authorization:Bearer {token}'
```

#### Implicit flow

Similar to code flow, except for the the `access token` which we we get back with the redirection.
For implicit flow, you can use [this url](http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=token&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=random_string)

#### OpenID and OAuth2 response_type & scope

According to the sharing web blog titled [Diagrams of All The OpenID Connect Flows](https://medium.com/@darutk/diagrams-of-all-the-openid-connect-flows-6968e3990660), we should pay attention to:

- `response_type` can be either `code, token, id_token`  or any combination of those attributes.
- `scope` might contain `openid`

Below are the potential combinations that are taken into account in SL until now:

```
response_type=code
    scope:
	    with `openid` in scope, return `id_token` at /token: OK
	    without: OK

response_type=token
    scope:
	    with and without `openid`, nothing to do: OK

response_type=id_token
    return `id_token` in /authorization endpoint

response_type=id_token token
    return `id_token` in addition to `access_token` in /authorization endpoint

response_type=id_token code
    return `id_token` in addition to `authorization_code` in /authorization endpoint

```
