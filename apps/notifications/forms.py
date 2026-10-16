from django import forms

CHANNEL_CHOICES = [("SMS", "SMS"), ("EMAIL", "Email"), ("BOTH", "SMS and Email")]


class AnnouncementForm(forms.Form):
    channel = forms.ChoiceField(choices=CHANNEL_CHOICES, initial="BOTH")
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), max_length=1000)