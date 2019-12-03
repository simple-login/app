
## OAuth flow

Authorization code flow: 

http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=dvoQ6Jtv0PV68tBUgUMM035oFiZw57

Implicit flow:
http://localhost:7777/oauth/authorize?client_id=client-id&state=123456&response_type=token&redirect_uri=http%3A%2F%2Flocalhost%3A7000%2Fcallback&state=dvoQ6Jtv0PV68tBUgUMM035oFiZw57

Exchange the code to get the token with `{code}` replaced by the code obtained in previous step.

http -f -a client-id:client-secret http://localhost:7777/oauth/token grant_type=authorization_code code={code}

Get user info:

http http://localhost:7777/oauth/user_info 'Authorization:Bearer {token}'


## Template structure

base
    single: for login, register page
    default: for all pages when user log ins
        
## How to create new migration

Whenever the model changes, a new migration needs to be created

Set the database connection to use staging environment:

> ln -sf ~/config/simplelogin/staging.env .env

Generate the migration script and make sure to review it:

> flask db migrate

## Code structure

local_data/: contain files used only locally. In deployment, these files should be replaced.
    - jwtRS256.key: generated using 
    
```bash
ssh-keygen -t rsa -b 4096 -m PEM -f jwtRS256.key
# Don't add passphrase
openssl rsa -in jwtRS256.key -pubout -outform PEM -out jwtRS256.key.pub
```

## OpenID, OAuth2 response_type & scope

According to https://medium.com/@darutk/diagrams-of-all-the-openid-connect-flows-6968e3990660

- `response_type` can be either `code, token, id_token`  or any combination.
- `scope` can contain `openid` or not

Below is the different combinations that are taken into account until now:

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
   

## API endpoints for extension

```
GET /alias/options hostname?="www.groupon.com"
	recommendation?:
		alias: www_groupon_com@simplelogin.co
		hostname: www.groupon.com

	custom?: 
		suggestion: www_groupon_com
		suffix: [@my_domain.com, .abcde@simplelogin.co]

	can_create_custom: true
	can_create_random: true

	existing:
		[email1, email2, ...]

POST /alias/custom/new
	prefix: www_groupon_com
	suffix: @my_domain.com

	201 -> OK {alias: "www_groupon_com@my_domain.com"}
	409 -> duplicated

POST /alias/random/new
	201 -> OK {alias: "random_word@simplelogin.co"}

```




