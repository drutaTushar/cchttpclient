
# New Features to Add
- [X] Implement Edit Command feature where user can edit commands especially request/response handlers
- [X] Persistent Credentials across mutliple executions of commands. Provide an ability where credentials or cookies etc are saved in response handlers and made available to next command executions via Named Credentials. Also do not restrict this feature only for Credentials but also support it for storing other state for eg. current user id etc. This allows user to carry context across mutliple commands
- [ ] Add abstraction of Messages - IF any error occurs, response hadlers can respond with meaningful messages which LLM can consume. Also Add better error reporting. remove default error traceback output. Add http status code, status line and body.