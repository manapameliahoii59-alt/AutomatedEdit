from app.data.api.api import demo_api

class AuthService:
    def login(self, username, password, captcha, sms_code):
        # In a real app, this would be an async call or return a future.
        # Since we use TaskManager in ViewModel, this just needs to be the synchronous blocking call.
        return demo_api.login(username, password, captcha, sms_code)

    def get_captcha(self):
        return demo_api.get_captcha()
