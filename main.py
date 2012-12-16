#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import webapp2
import jinja2
import os
import hashlib
import logging

from google.appengine.ext import db
from google.appengine.api import mail
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
from google.appengine.api import taskqueue

# load the templating environment.
jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

class MainHandler(webapp2.RequestHandler):
    
    def get(self):
        # self.response.write('Hello world!')
        templateValues = {'color' : 'yellow'}
        template = jinja_environment.get_template('web_templates/index.html')
        self.response.out.write(template.render(templateValues))
        
        
class RegisterHandler(webapp2.RequestHandler):
    
    def post(self):
        
        email = self.request.get('email').strip()
        
        # check if there is already an account with that email
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE email = '%s'" % email)
        if registrations.count() > 0:
            templateValues = {'email' : email }
            template = jinja_environment.get_template('web_templates/email_in_use.html')
            self.response.out.write(template.render(templateValues))
            return
        
        
        # create a new account
        registration = Registration()
        registration.regKey = hashlib.md5(email + '-banana').hexdigest();
        registration.email = email
        registration.firstName = self.request.get('first_name')
        registration.dharmaName = self.request.get('dharma_name')
        registration.nextTraining = int(self.request.get('first_training'))
        registration.sinceLastResponse = 0
        registration.emailValidated = False
        registration.put();
        
        # send validation email
        host = self.request.environ["HTTP_HOST"]
        message = mail.EmailMessage()
        message.to = email
        message.sender = "Trainings Reminder Service <rogerhyam@googlemail.com>"
        message.subject = "Confirm your registration"
        
        templateValues = {'confirmUri' : 'http://%s/confirm?reg_key=%s' % (host, registration.regKey)}
        
        template = jinja_environment.get_template('email_templates/confirm.txt')
        message.body = template.render(templateValues)
        
        template = jinja_environment.get_template('email_templates/confirm.html')
        message.html = template.render(templateValues)
        
        message.send()
        
        # display thanks - please validate page
        templateValues = {'color' : 'yellow'}
        template = jinja_environment.get_template('web_templates/please_validate.html')
        self.response.out.write(template.render(templateValues))

class ConfirmHandlerWeb(webapp2.RequestHandler):
    
    def get(self):
        
        regKey = self.request.get('reg_key')
        message = ''
        title = ''
        reg = None
        
        # try and get the registration from the store
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE regKey = '%s'" % regKey)
        
        # if we don't have a reg then report that they should try registering again
        if registrations.count() == 0:
            title = "Registration Not Found"
            message = "We can't find a registration associated with the registration key %s. Perhaps it has already been deleted or the link is corrupt?" % regKey
        else:
            reg = registrations[0]
            reg.sinceLastResponse = 0
            
            # if we find one and it is already validated they must be just confirming
            if reg.emailValidated:
                title = "Registration Reconfirmed"
                message = "Thanks for reconfirming your registration. You will receive one email a week for ten weeks unless you ask to cancel them."
            else:
                # if we find one and it is validated then validated it and report
                reg.emailValidated = True
                title = "Registration Confirmed"
                message = "Thanks for confirming your email address. You will now receive one email a week for ten weeks unless you ask to cancel them."
        
        reg.put()
                
        # Tell them about it
        host = self.request.environ["HTTP_HOST"]
        templateValues = {'message' : message, 'title' : title, 'reg' : reg, 'cancelUri' : 'http://%s/cancel?reg_key=%s' % (host, regKey) }
        template = jinja_environment.get_template('web_templates/confirm.html')
        self.response.out.write(template.render(templateValues))
        

class CancelHandler(webapp2.RequestHandler):

    def get(self):

        regKey = self.request.get('reg_key')
        message = ''

        # try and get the registration from the store
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE regKey = '%s'" % regKey)

        # if we don't have a reg then report that they should try registering again
        if registrations.count() == 0:
            reg = False
        else:
            reg = registrations[0]
           
        # Tell them about it
        templateValues = {'title' : 'Cancel Registration', 'reg' : reg}
        template = jinja_environment.get_template('web_templates/cancel.html')
        self.response.out.write(template.render(templateValues))

class DoCancelHandler(webapp2.RequestHandler):

    def get(self):
        regKey = self.request.get('reg_key')
        message = ''
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE regKey = '%s'" % regKey)
        
        if registrations.count() > 0:
            reg = registrations[0]
            reg.delete()
        
        templateValues = {'title' : 'Registration Cancelled'}
        template = jinja_environment.get_template('web_templates/cancel_done.html')
        self.response.out.write(template.render(templateValues))

class PublishAllHandler(webapp2.RequestHandler):

    def get(self):
        
        # get all the registrations in the system and make a job to mail to each one
        keys = Registration.all(keys_only=True);
        for key in keys:
            # Add the task to the default queue.
            taskqueue.add(url='/tasks/publish_one', params={'key': key})

class PublishOneHandler(webapp2.RequestHandler):
    
    def post(self): # should run in 1s ?
        key = self.request.get('key')
        reg = Registration.get(key)
        
        # if there is no reg associates with key crap out
        if reg == None: return
        
        # if the registration has expired then delete it and crap out
        if reg.sinceLastResponse > 9:
            reg.delete()
            return
        
        # if the email has not be validated the ignore it but increment count so it 
        # will eventually be deleted
        if reg.emailValidated == False:
            reg.sinceLastResponse = reg.sinceLastResponse + 1
            return
            
        # if the registration is OK then send an email
        message = mail.EmailMessage()
        message.to = reg.email
        host = self.request.environ["HTTP_HOST"]
        message.sender = "Mindfulness Trainings<rogerhyam@googlemail.com>"
        
        if reg.nextTraining == 1: message.subject = 'Mindfulness Training 1: Reverence For Life'
        elif reg.nextTraining == 2: message.subject = 'Mindfulness Training 2: True Happiness'
        elif reg.nextTraining == 3: message.subject = 'Mindfulness Training 3: True Love'
        elif reg.nextTraining == 4: message.subject = 'Mindfulness Training 4: Loving Speech and Deep Listening'
        elif reg.nextTraining == 5: message.subject = 'Mindfulness Training 5: Nourishment and Healing'
        else: message.subject = 'ERROR: Trying to send Mindfulness Training number 6!'
        
        
        templateValues = {
            'confirmUri' : "http://%s/confirm?reg_key=%s" % (host, reg.regKey),
            'cancelUri': "http://%s/cancel?reg_key=%s" % (host, reg.regKey),
            'reg' : reg
            }

        template = jinja_environment.get_template("email_templates/training_%i.txt" % reg.nextTraining )
        message.body = template.render(templateValues)

        template = jinja_environment.get_template("email_templates/training_%i.html" % reg.nextTraining)
        message.html = template.render(templateValues)

        message.send()
        
        # update the registration ready to send next week
        nt = reg.nextTraining
        if nt == 5: reg.nextTraining = 1
        else: reg.nextTraining = nt + 1
        
        # up count since last heard from them
        reg.sinceLastResponse = reg.sinceLastResponse + 1
        
        # save the changes
        reg.put()
        
class ViewMailHandler(webapp2.RequestHandler):

    def get(self):
        
        regKey = self.request.get('reg_key')
        training = self.request.get('training')
        
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE regKey = '%s'" % regKey)
        reg = registrations[0]
        
        host = self.request.environ["HTTP_HOST"]
        templateValues = {
            'confirmUri' : "http://%s/confirm?reg_key=%s" % (host, reg.regKey),
            'cancelUri': "http://%s/cancel?reg_key=%s" % (host, reg.regKey),
            'reg' : reg
            }
        template = jinja_environment.get_template("email_templates/training_%s.html" % training )
        self.response.out.write(template.render(templateValues))

class TestMailHandler(webapp2.RequestHandler):

    def get(self):
        regKey = self.request.get('reg_key')
        registrations = db.GqlQuery("SELECT * FROM Registration WHERE regKey = '%s'" % regKey)
        reg = registrations[0]
        taskqueue.add(url='/tasks/publish_one', params={'key': reg.key() })
        self.response.out.write("Mail Task Queued")

class Registration(db.Model):
    """Models an individual registration"""
    regKey = db.StringProperty()
    email = db.EmailProperty()
    firstName = db.StringProperty()
    dharmaName = db.StringProperty()
    nextTraining = db.IntegerProperty()
    sinceLastResponse = db.IntegerProperty()
    emailValidated = db.BooleanProperty();
    created = db.DateTimeProperty(auto_now_add = True)
    modified = db.DateTimeProperty(auto_now = True)
    

app = webapp2.WSGIApplication([
    ('/', MainHandler),
    ('/register', RegisterHandler),
    ('/confirm', ConfirmHandlerWeb),
    ('/cancel', CancelHandler),
    ('/cancel_doit', DoCancelHandler),
    ('/view_mail', ViewMailHandler),
    ('/test_mail', TestMailHandler),
    ('/tasks/publish_all', PublishAllHandler),
    ('/tasks/publish_one', PublishOneHandler)
    
], debug=True)
