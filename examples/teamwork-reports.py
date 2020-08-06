"""
This project requires the python-teamwork package available from:

    https://github.comu/cybertoast/python-teamwork

This example file uses the above version of python-teamwork to fetch content
from a Teomwork account
"""

import teamwork 
from pprint import pprint
import os
import sys 
import re
import json
import click
import csv
import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


def fetch_project_summary(tw):
    status_projects = []

    for project in tw.get_projects():
        # Ignore all non-Tech projects
        if not re.match("tech.*ticket", project.get("name", ""), re.I):
            continue

        status_projects.append(
            {
                "id": project.get("id"),
                "name": project.get("name"),
                "completed": 0,
                "progress": 0,
            }
        )
        
        for task in tw.get_tasks_for_project(project.get("id")):
            print(task.get("name"))
            pass

        print("[%s] ==[ %s ]==> %s to %s" % 
            (project.get("name"), project.get("progress"), project.get("startDate"), project.get("endDate"))
        )

def reconcile_projects(wrike_projects, tw_projects):
    missing = set(wrike_projects) - set(tw_projects)
    return missing

def update_due_dates(tw_projects):
    for project in tw_projects:
        # Fetch the tasks in this project
        print(project)

        # for task in fetch_tasks_for_project(project_id):
    
def test_update_task(tw):
    tw.update_task(task_id=17041155, data={"due-date": 20210315})


def save_to_gsheet(summary, credentials_file, config):
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_file, config.get("SCOPES"))
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)
    write_data_to_gsheet(service, summary, config)

def write_data_to_gsheet(service, values, config):
    # Update the data
    body = {
        'values': values
    }
    # https://developers.google.com/sheets/api/reference/rest/v4/ValueInputOption
    value_input_option = "USER_ENTERED"
    result = service.spreadsheets().values(
    ).update( 
        spreadsheetId=config.get("SPREADSHEET_ID"), 
        range=config.get("RANGE_NAME"), 
        valueInputOption=value_input_option, body=body
    ).execute()

    print('{0} cells updated.'.format(result.get('updatedCells')))


@click.command()
@click.option('--all-tasks', is_flag=True, help="Get all tasks")
@click.option('--all-projects', is_flag=True, help="Get all projects")
@click.option('--summary', is_flag=True, help="Get summary report")
@click.option('--include-projects', is_flag=True, 
              help="Include list of projects in the output") 
@click.option('--tags', help='Project Tags to filter to.', multiple=True)
@click.option('--portfolios', 
              help='Portfolios to filter to. Pass in blank "" or ".*" for all',
              multiple=True)
@click.option('--saveto', type=click.File("w"), 
              help="Name of file to save output date to")
@click.option('--format', help="Output format", default="json",
              type=click.Choice(['json', 'csv', 'gsheet'], 
              case_sensitive=False))
@click.option('--credentials-file', help="Google credentials.json path") 
@click.option('--config-file', 
              help=("Path to configuration file. See the config.json.sample file "
                    "in this repo for example structure"), 
              required=True, type=click.File("r")) 
def main(all_tasks, all_projects,
         summary, include_projects, tags, portfolios, 
         saveto, format, credentials_file, config_file):
    """Python script to demonstrate connection with the teamwork-python module

    The script is primarily used to fetch teamwork content in a consistent 
    data format - ie, CSV, JSON, and Google Sheets.

    A useful process is to fetch all your tasks and put them into a Google Sheet:

        python teamwork-reports.py \
            --config_file config.json \
            --all-tasks --format gsheet \
            --credentials_file /path/to/credentials.json 

    """
    config = json.loads(config_file.read())    
    tw = teamwork.Teamwork(config.get("TEAMWORK_DOMAIN"), config.get("TEAMWORK_API_KEY"))
    tw.include_projects_in_summary = include_projects
    tw.output_format = format

    if all_tasks:
        summary = tw.get_tasks(include_portfolios=True)
    elif all_projects:
        summary = tw.get_projects()
    elif summary:
        if portfolios:
            summary = tw.get_summary_for_portfolios(portfolios)
        elif tags:
            summary = tw.get_summary_for_tags(tags)

    if format == "json": 
        json.dump(summary, saveto or sys.stdout)
    elif format == "csv":
        writer = csv.writer(saveto)
        writer.writerows(summary)
    elif format == "gsheet":
        save_to_gsheet(summary, credentials_file, config)


if __name__ == "__main__":
    main()
