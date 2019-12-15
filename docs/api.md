# API

For now the only API client is the Chrome/Firefox extension. This extension relies on `API Code` for authentication. 

In every request the extension sends

- the `API Code` is set in `Authentication` header. The check is done via the `verify_api_key` wrapper, implemented in `app/api/base.py`

- the current website `hostname` which is the website subdomain name + domain name. For ex, if user is on `http://dashboard.example.com/path1/path2?query`, the subdomain is `dashboard.example.com`. This information is important to know where an alias is used in order to proposer to user the same alias if they want to create on alias on the same website in the future. The `hostname` is passed in the request query `?hostname=`, see `app/api/views/alias_options.py` for an example.

Currently the latest extension uses 2 endpoints:

- `/alias/options`: that returns what to suggest to user when they open the extension. 

```
GET /alias/options hostname?="www.groupon.com"

Response: a json with following structure. ? means optional field.
	recommendation?:
		alias: www_groupon_com@simplelogin.co
		hostname: www.groupon.com

	custom: 
		suggestion: groupon
		suffix: [@my_domain.com, .abcde@simplelogin.co]

	can_create_custom: true

	existing:
		[email1, email2, ...]
```

- `/alias/custom/new`: allows user to create a new custom alias.

```
POST /alias/custom/new
	prefix: www_groupon_com
	suffix: @my_domain.com

Response:
	201 -> OK {alias: "www_groupon_com@my_domain.com"}
	409 -> duplicated

```

