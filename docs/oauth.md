# OAuth flow

SL currently supports code and implicit flow.

## Code flow

To trigger the code flow locally, you can go to the following url after running `python server.py`:  

```
http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=random_string
```

You should see there the authorization page where user is asked for permission to share their data. Once user approves, user is redirected to this url with an `authorization code`: `http://localhost:7000/callback?state=123456&code=the_code`

Next, exchange the code to get the token with `{code}` replaced by the code obtained in previous step. The `http` tool used here is https://httpie.org

```
http -f -a client-id:client-secret http://localhost:7777/oauth/token grant_type=authorization_code code={code}
```

This should return an `access token` that allow to get user info via the following command. Again, `http` tool is used.

```
http http://localhost:7777/oauth/user_info 'Authorization:Bearer {token}'
```

## Implicit flow

Similar to code flow, except we get the `access token` back with the redirection. 
For implicit flow, the url is 

```
http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=token&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=random_string
```

## OpenID, OAuth2 response_type & scope

According to https://medium.com/@darutk/diagrams-of-all-the-openid-connect-flows-6968e3990660

- `response_type` can be either `code, token, id_token`  or any combination.
- `scope` can contain `openid` or not

Below is the different combinations that are taken into account in SL until now:

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
   