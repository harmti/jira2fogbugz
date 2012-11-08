#!/usr/bin/env python
import argparse
import sys
import time
import traceback
from jira.client import JIRA
from jira.exceptions import JIRAError
from fogbugz import FogBugz
from fogbugz import FogBugzLogonError, FogBugzConnectionError

RECENTLY_ADDED_CASES = {}

FOGBUGZ_FIELDS = ('ixBug,ixPersonAssignedTo,ixPersonEditedBy,'
                  'sTitle,sLatestTextSummary,sProject,dtOpened,'
                  'sCategory,ixBugParent,hrsCurrEst,tags')

def create_issue(jis, email_map, project, default_assignee):
    global RECENTLY_ADDED_CASES
    data = {}
    parent_issue = None
    if not getattr(jis.fields, 'assignee', False):
        data['ixPersonAssignedTo'] = default_assignee
    else:
        data['ixPersonAssignedTo'] = email_map[jis.fields.assignee.emailAddress]
    data['sTitle'] = jis.fields.summary if jis.fields.summary else 'No title'
    description = ''
    if jis.fields.description:
        description = jis.fields.description
    data['sEvent'] = description
    data['sProject'] = project
    # TODO: use pytz and convert timezone data properly
    data['dt'] = jis.fields.created.split('.')[0]+'Z'
    data['hrsCurrEst'] = 0
    tags = []
    if getattr(jis.fields, 'fixVersions', []):
        for ver in jis.fields.fixVersions:
            tags.append(ver.name)
    if getattr(jis.fields, 'labels', []):
        for label in jis.fields.labels:
            if label != u'export':
                tags.append(label)
    if tags:
        data['sTags'] = ','.join(tags)
    if getattr(jis.fields, 'timeoriginalestimate'):
        data['hrsCurrEst'] = int(jis.fields.timeoriginalestimate)/60/60
    # TODO: these are custom issue types in JIRA imported from Pivotal Tracker
    #       so you have to make a special mapping
    if jis.fields.issuetype.name in ('Story', 'Improvement', 'Epic', 'Theme', 'Technical task'):
        data['sCategory'] = 'Feature'
    elif jis.fields.issuetype.name in ('Bug'):
        data['sCategory'] = 'Bug'
    else:
        raise Exception("Unknown issue type: {0}".format(jis.fields.issuetype.name))

    if getattr(jis.fields, 'parent', None):
        parent = jis.fields.parent
        tmp = jira.search_issues('key={0}'.format(parent.key))
        if len(tmp) != 1:
            raise Exception("Was expecting to find 1 result for key={0}. Got {1}".format(parent.key, len(tmp)))
        parent_issue = create_issue(tmp[0])
        data['ixBugParent'] = parent_issue

    if jis.fields.issuelinks:
        for link in jis.fields.issuelinks:
            parent = getattr(link, 'outwardIssue', None)
            child = getattr(link, 'inwardIssue', None)
            if parent:
                tmp = jira.search_issues('key={0}'.format(parent.key))
                if len(tmp) != 1:
                    raise Exception("Was expecting to find 1 result for key={0}. Got {1}".format(parent.key, len(tmp)))
                parent_issue = create_issue(tmp[0],
                                            email_map,
                                            project,
                                            default_assignee)
                data['ixBugParent'] = parent_issue

    func = fb.new
    tries = 0
    count = 0
    # TODO: create custom field with JIRA key and JIRA URL then search for them
    #       before you attempt to create a new case
    if RECENTLY_ADDED_CASES.has_key(jis.key):
        resp = fb.search(q=RECENTLY_ADDED_CASES[jis.key],
                         cols=FOGBUGZ_FIELDS)
        count = int(resp.cases['count'])
        if count != 1:
            raise Exception("We should see case {0}".format(RECENTLY_ADDED_CASES[jis.key]))

    if count == 1:
        case = resp.cases.case
        data.pop('sEvent')
        sparent_issue = parent_issue if parent_issue else 'n/a'
        print "{0} exists as case ID {1: >3} ... parent case {2: >3} Type={3}".format(jis.key, case.ixbug.string, sparent_issue, jis.fields.issuetype.name)
        if int(case.ixpersonassignedto.string) == data['ixPersonAssignedTo']:
            data.pop('ixPersonAssignedTo')
        curr = case.stitle.string
        if curr[-3:] == '...':
            curr = curr[:-3]
        if curr in data['sTitle']:
            data.pop('sTitle')
        if case.sproject.string == data['sProject']:
            data.pop('sProject')
        if data.get('ixBugParent', False):
            if int(case.ixbugparent.string) == data['ixBugParent']:
                data.pop('ixBugParent')
        if case.scategory.string == data['sCategory']:
            data.pop('sCategory')
        if int(case.hrscurrest.string) == data['hrsCurrEst']:
            data.pop('hrsCurrEst')
        tags = [tag.string for tag in resp.cases.case.tags.childGenerator()]
        if data.has_key('sTags'):
            new_tags = []
            split_tags = data['sTags'].split(',')
            for t in split_tags:
                if t not in tags:
                    new_tags.append(t)
            if new_tags:
                data['sTags'] = ','.join(new_tags)
        data.pop('dt')
        if not data:
            return int(case['ixbug'])
        data['ixBug'] = int(case['ixbug'])
        func = fb.edit
        print "Calling edit with {0}".format(data)
    else:
        sparent_issue = parent_issue if parent_issue else 'n/a'
        print "{0} doesn't exist yet ... parent case {1: >3} Type={2}".format(jis.key, sparent_issue, jis.fields.issuetype.name)
        reporter = getattr(jis.fields, 'reporter', None)
        if reporter:
            data['ixPersonEditedBy'] = email_map[reporter.emailAddress]
        else:
            data['ixPersonEditedBy'] = default_assignee
        print "Creating new"
    return 0

def get_jira_issues(server, query):
    chunk_size = 100
    start_at = 0
    while True:
        issues = server.search_issues(query,
                                      startAt=start_at,
                                      maxResults=chunk_size)
        if not issues:
            break
        start_at += chunk_size
        for issue in issues:
            yield issue

def run():
    parser = argparse.ArgumentParser(description="JIRA to FogBugz importer")
    parser.add_argument('jira_url',
                        help="JIRA URL, ex. http://jira.example.com")
    parser.add_argument('jira_username', help="JIRA username")
    parser.add_argument('jira_password', help="JIRA password")
    parser.add_argument('fogbugz_url',
                        help="FogBugz URL, ex. http://example.fogbugz.com")
    parser.add_argument('fogbugz_username', help="FogBugz username")
    parser.add_argument('fogbugz_password', help="FogBugz password")
    parser.add_argument('default_assignee', help="The email of the default assignee")
    # TODO: dynamically create projects based on JIRA data
    parser.add_argument('project', help="Which FogBugz project to put cases in")
    parser.add_argument('-v', '--verbose',
                        dest="verbose",
                        action="store_true",
                        default=False,
                        help="Get more verbose output")
    args = parser.parse_args()

    try:
        try:
            jira = JIRA(options={'server': args.jira_url},
                        basic_auth=(args.jira_username,
                                    args.jira_password))
        except JIRAError, e:
            if e.status_code == 403:
                sys.stderr.write('Cannot connect to JIRA. Check username/password\n')
                sys.exit(1)
            else:
                msg = "Cannot connect to JIRA  (return code={0})".format(e.status_code)
                if args.verbose:
                    msg += "\n{0}".format('Response from JIRA:\n{0}'.format(e.text))
                sys.stderr.write(msg+'\n')
                sys.exit(1)
        try:
            fb = FogBugz(args.fogbugz_url)
            fb.logon(args.fogbugz_username, args.fogbugz_password)
        except FogBugzConnectionError:
            sys.stderr.write('Cannot connect to FogBugz\n')
            sys.exit(1)
        except FobBugzLogonError:
            sys.stderr.write('Cannot login to FogBugz. Check username/password')
            sys.exit(1)

        # initialize an email to fogbugz User ID mapping
        email_map = {}
        resp = fb.listPeople()
        for person in resp.people.childGenerator():
            email_map[person.semail.string] = int(person.ixperson.string)
        try:
            default_assignee = email_map[args.default_assignee]
        except KeyError:
            parser.error("Default assignee {0} does not exist in FogBugz".format(args.default_assignee))

        for issue in get_jira_issues(jira, query):
            create_issue(fb, issue, project_name, email_map, default_assignee)
    except SystemExit:
        raise
    except:
        sys.stderr.write("Unknown error occurred\n")
        traceback.print_exc(sys.stderr)
        sys.exit(1)
    return sys.exit(0)

if __name__ == '__main__':
    run()
