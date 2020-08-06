import requests
import json
from datetime import datetime
import sys
import time
import re
import logging
import arrow


# Helper Functions
def spinning_cursor():
    while True:
        for cursor in '|/-\\':
            yield cursor

def timedelta_to_hours_minutes(td):
    return td.seconds // 3600, (td.seconds // 60) % 60


def time_to_hhmm(time_input):
    return '%i:%i' % (time_input.hour, time_input.minute)


class User(object):
    def __init__(self, id):
        self.id = id


class Teamwork(object):
    """
    Basic wrapper to work with the Teamwork API
    Based on Teamwork API: http://developer.teamwork.com/
    """
    def __init__(self, domain, api_key):
        self._init_vars(domain, api_key)
        self._init_logger()

    def _init_vars(self, domain, api_key):
        self._domain = domain
        self._api_key = api_key
        self._account = self.authenticate()
        self._user = User(self._account.get('userId'))
        self.tags = None
        self.portfolio_boards = None
        self.spinner = spinning_cursor()
        # Should the reports output include projects list?
        self.include_projects_in_summary = False
        self.output_format = "json"

    def _init_logger(self):
        # This can be overridden by the caller
        # Console Handler for logger.
        ch = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            '[%(asctime)s][%(levelname)s][%(filename)s:%(funcName)s] %(message)s')
        ch.setFormatter(formatter)

        self.logger = logging.getLogger()
        self.logger.setLevel(logging.WARNING)
        self.logger.addHandler(ch)
        self.logger.info("Logger initialized")

    def get(self, path=None, params=None):
        url = self.get_base_url()
        if path:
            url = "%s/%s" % (url, path)
        payload = {}

        if params:
            payload = params

        resp = requests.get(
            url, auth=(self._api_key, ''), params=payload)

        assert resp.status_code==200, f"[{resp.status_code}][{str(resp)}] Error fetching from URL: {url}"
        
        return resp.json()

    def put(self, path=None, data=None):
        url = self.get_base_url()
        if path:
            url = "%s/%s" % (url, path)

        request = requests.put(
            url, auth=(self._api_key, ''), json={'todo-item': data})

        if request.status_code != 200:
            raise RuntimeError("[%s] %s" % (request.status_code, request.reason))

        return request.text

    def post(self, path=None, data=None):
        url = self.get_base_url()
        if path:
            url = "%s/%s" % (url, path)

        request = requests.post(
            url, auth=(self._api_key, ''), json=data)

        if request.status_code != 201:
            raise RuntimeError("[%s] %s" % (request.status_code, request.reason))

        return request.text

    def get_base_url(self):
        return 'https://%s' % self._domain

    def authenticate(self):
        result = self.get('authenticate.json')
        return result.get('account')

    def get_projects(self, payload={}):
        if ("includeProjectOwner") not in payload.keys():
            payload["includeProjectOwner"] = True
        result = self.get('projects.json', params=payload)
        return result.get('projects')
    
    def get_project_summary(self, project_id: int):
        """
        Get summary for the project

        https://developer.teamwork.com/projects/api-v3/ref/summary/get-projects-api-v3-projects-projectid-summaryjson
        GET /projects/api/v3/projects/{projectId}/summary.json

        :param: project_id: Project ID
        :returns: Project summary as an object
        :rtype: object
        """
        result = self.get(f"/projects/{project_id}/summary.json") 
        return result.get('summary')

    def get_project_times(self, project_id, user_id=None, start_date=None,
                          end_date=None):
        """
        Get project time entries from project

        http://developer.teamwork.com/timetracking#retrieve_all_time
        GET /projects/{project_id}/time_entries.json

        :param: user_id: User id
        :param: start_date: Start date
        :param: end_date: End Date

        :type user_id: int
        :type start_date: datetime.datetime
        :type end_date: datetime.datetime

        :returns: List of time entries
        :rtype: list
        """
        payload = {}
        if start_date:
            payload['fromdate'] = start_date.strftime('%Y%m%d')
        if end_date:
            payload['todate'] = end_date.strftime('%Y%m%d')
        if user_id:
            payload['userId'] = user_id

        result = self.get("/projects/%i/time_entries.json" % project_id,
                          params=payload)
        return result.get('time-entries')

    def save_project_time_entry(self, project_id, entry_date, duration,
                                user_id, description, start_time):
        """
        :param: project_id: Project ID
        :param: date: datetime.date Date of time entry
        :param: duration: datetime.timedelta Duration
        :param: user_id: Integer Id of person
        :param: description: String Id of person
        :param: start_time: datetime.timedelta
        """
        duration_hours, duration_minutes = timedelta_to_hours_minutes(duration)

        data = {
                    "time-entry": {
                        "description": description,
                        "person-id": user_id,
                        "date": entry_date.strftime('%Y%m%d'),
                        "time": time_to_hhmm(start_time),
                        "hours": duration_hours,
                        "minutes": duration_minutes,
                        "isbillable": "1"
                    }
                }
        result = self.post(
            '/projects/%i/time_entries.json' % project_id,
            data=data)
        return result

    def get_time_entry(self, time_id):
        result = self.get('time_entries/%i.json' % time_id)
        return result.get('time-entry')

    def update_time_entry(self):
        pass

    def delete_time_entry(self):
        pass

    def update_project_time(self, project_id, data):
        pass

    def get_project_user_times(self, project_id, user_id):
        pass

    def update_project_ownerid(self, project_id, owner_id):
        self.put('/projects/%i.json' % project_id, 
                 data={"project": { "projectOwnerId": owner_id}})

    def get_tasks(self, include_portfolios=False):
        """Get all tasks across all projects

        Parameters
        ----------
        include_portfolios : bool, optional
            whether to add the portfolio association into the projects, as a list. 
            By default False.

        Returns
        -------
        List of Bbjects
            Returns JSON object of all the tasks
            
        """
        tasks = []
        page = 0
        while True:
            page += 1
            # We want to keep looping until there are no more tasks, since
            # the tasks api returns 250 at a time paginated 
            payload = {
                "includeCompletedTasks": True,
                "includeCompletedSubtasks": True,
                "getSubTasks": "no",
                "page": page, "pageSize": 250
            }
            result = self.get('tasks.json', params=payload)
            tasks_page = result.get("todo-items")
            if not tasks_page or len(tasks_page) == 0:
                # No more tasks to fetch
                break
            tasks.extend(tasks_page)

        if include_portfolios:
            projects = self.get_projects(payload={"include": ["portfolioBoards"]})
        
            for task in tasks:
                # Get the project for this task and add in the portfolioBaords
                # TODO: Why the F is project.id a str and task.project-id an int?! 
                # TODO: Notify Teamwork of this inconsistency
                project = next((project for project in projects 
                                if project.get("id") == str(task.get("project-id"))), None)
                task["portfolioBoards"] = project.get("portfolioBoards")
                task["project-start-date"] = project.get("startDate")
                task["project-status"] = project.get("startDate")
                task["project-end-date"] = project.get("endDate")
                task["project-owner"] = project.get("owner")

        if self.output_format == "json":
            return tasks
        
        elif self.output_format in ["gsheet", "csv"]:
            headers = [
                "id", "content", "status", "completed", "start-date", "due-date", 
                "progress", "estimated-minutes", 
                "creator-firstname", "creator-lastname", "project-id", "project-name", "project-owner", "project-start-date", "project-end-date", 
                "responsible-party-names",
                "portfolioBoards"
            ]
            csv_out = []
            csv_out.append(headers)
            for task in tasks:
                row = []
                for header in headers:
                    if header == "portfolioBoards":
                        cell = ",".join([pboard.get("board").get("name") for pboard in task.get(header)])
                    elif header == "project-owner":
                        if task.get(header):
                            cell = task.get(header, {}).get("fullName")
                    else:
                        cell = task.get(header)
                    row.append(cell)
                csv_out.append(row)
            
            return csv_out

    def get_portfolios():
        payload = {
            "includeCompletedTasks": True,
            "includeCompletedSubtasks": True,
            "getSubTasks": "no",
        }
        result = self.get("portfolio/boards.json")
        portfolio_boards = result.get("boards", params=payload)
        
        return portfolio_boards

    def get_tasks_for_project(self, project_id):
        assert project_id, "Cannot retrieve tasks for undefined project-id"

        payload = {
            "includeCompletedTasks": True,
            "includeCompletedSubtasks": True
        }
        result = self.get('projects/%s/tasks.json' % project_id, params=payload)
        tasks = result.get("todo-items")

        return tasks

    def update_task(self, task_id, data):
        result = self.put('tasks/%s.json' % task_id, data=data)

    def create_project(self, data):
        result = self.post('projects.json', data=data)

    def get_summary_for_tags(self, tag_names=[]):
        """
        Get summary of tasks, progress, and estimates by tag value

        * Get list of projects matching a tag
        * For each project get project summary

        :param tags: list of tag names
        :returns: object containing summary
        """

        tags = self._tags_by_name(tag_names) 
        tag_summaries = []

        sys.stderr.write("\033[K") # Clear to the end of line
        self.logger.info("Summarizing %s tags\r" % (len(tags)), end="", file=sys.stderr)

        for tag in tags:
            tag_summary = {}
            tag_summary["name"] = tag.get("name")
            tag_summary["name"] = tag.get("id")
            projects = self.get_projects(
                payload={"projectTagIds" : ",".join([tag.get("id") for tag in tags])}
            )
            projects_summary = self._summarize_projects(projects)
            tag_summary["summary"] = projects_summary
            tag_summaries.append(tag_summary)

        return tag_summaries
    
    def get_summary_for_portfolios(self, portfolios):
        """
        Fetch the project summary for a portfolio-name

        :param portfolio_name: Either full or regex name of the portfolio
        :returns Summary Object
        """
        # Get the portfolio id
        boards = self._portfolios_by_name(portfolios)
        self.logger.info("Summarizing %s Portfolio Boards\r" % (len(boards)))

        board_summaries = []
        summary_fields = [
            "id", "name",
            # The remaining fields come from the _summarize_projects() method
            "start-date", "due-date", "progress",
            "progress-percent", "estimated-minutes", "tasks", 
            "completed", "completed-percent", "active", "late"
        ]

        if self.output_format in ["gsheet", "csv"]:
            # Add the header row
            board_summaries.append(summary_fields) 
            
        for board in boards:
            projects = self._projects_in_portfolio_board(board.get("id")) 
            projects_summary = self._summarize_projects(projects)

            if self.output_format == "json":
                board_summary = {}
                board_summary["name"] = board.get("name")
                board_summary["id"] = board.get("id")
                board_summary["summary"] = projects_summary
                board_summaries.append(board_summary)
            elif self.output_format in  ["csv", "gsheet"]:
                projects_values = [projects_summary.get(fieldname) for fieldname in summary_fields[2:]]
                projects_values = [board.get("id"), board.get("name")] + projects_values
                board_summaries.append(projects_values) 

        return board_summaries

    #--------------------------------------------
    # Internal / Private methods
    #--------------------------------------------
    def _projects_in_portfolio_board(self, board_id):
        result = self.get("/portfolio/boards/%s/columns.json" % board_id)
        projects = []
        for column in result.get("columns"):
            result = self.get("/portfolio/columns/%s/cards.json" % column.get("id"))
            # The cards are not true projects, so let's just send the project-id from them
            project_ids = [card.get("projectId") for card in result.get("cards")]
            if not project_ids:
                # Don't process blank project-id's since otherwise
                # the projects list below will fetch all projects
                continue

            # Fetch the projects 
            result = self.get("/projects/api/v3/projects.json", 
                              params={"projectIds": ",".join(project_ids)})
            projects.extend(
                [{
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "endDate": item.get("endDate"),
                    "startDate": item.get("startDate"),
                    "status": item.get("status")
                 } 
                 for item in result.get("projects")]
            )
        
        return projects


    def _summarize_projects(self, projects):
        summary = {
            "start-date": None,
            "due-date": None,
            "progress": 0,
            "progress-percent": 0,
            "estimated-minutes": 0,       # from estimated-minutes
            "tasks": 0,
            "completed": 0,     # based on status=deleted, completed, reopened, new
            "completed-percent": 0,
            "active": 0,        # based on status=deleted, completed, reopened, new
            "late": 0,          # calculated
            "projects": []
        }

        for project in projects:
            self._summarize_project(project, summary)
            self.logger.warn("Due-date: %s" % summary.get("due-date"))

        if summary["tasks"]:
            summary["progress-percent"] = summary["progress"] / (summary["tasks"] * 100)
            summary["completed-percent"] = summary["completed"] / (summary["tasks"])

        # Format the datetime fields
        if summary.get("start-date"): 
            summary["start-date"] = arrow.get(summary.get("start-date"), "YYYYMMDD").date()
        if summary.get("due-date"): 
            summary["due-date"] = arrow.get(summary.get("due-date"), "YYYYMMDD").date()

        return summary
    
    def _summarize_project(self, project, summary):
        tasks = self.get_tasks_for_project(project.get("id"))
        # No need to process empty projects
        if not len(tasks): return
        summary["tasks"] += len(tasks)

        self.logger.info("Summarizing %s tasks for project %s\r" % (
                len(tasks), tasks[0].get("project-name"))
        )

        if self.include_projects_in_summary and self.output_format == "json":
            # We don't want the projects details in CSV outputs
            summary["projects"].append({
                "name": project.get("name"),
                "id": project.get("id"),
                "startDate": project.get("startDate"),
                "endDate": project.get("endDate"),
                "status": project.get("status"),
                "subStatus": project.get("subStatus"),
            })

        today = int("%04d%02d%02d" % (datetime.today().year, 
                    datetime.today().month, 
                    datetime.today().day))

        for task in tasks:
            if task.get("start-date"):
                if not summary.get("start-date"):
                    summary["start-date"] = task.get("start-date") 
                if task.get("start-date") < summary.get("start-date"):
                    summary["start-date"] = task.get("start-date") 

            if task.get("due-date"):
                if not summary.get("due-date"):
                    summary["due-date"] = task.get("due-date")
                if task.get("due-date") > summary.get("due-date"):
                    summary["due-date"] = task.get("due-date") 
                
            if summary.get("due-date") and int(summary.get("due-date")) < today:
                summary["late"] += 1
            if task.get("status").startswith("complete") or task.get("completed") or task.get("progress") == 100:
                summary["completed"] += 1
            else:
                summary["active"] += 1
                    
            summary["progress"] += int(task.get("progress", 0))
            summary["estimated-minutes"] += int(task.get("estimated-minutes", 0))

            if str(summary["due-date"]).startswith("2024"): 
                breakpoint()
            self.logger.warn("Due-date: %s" % summary.get("due-date"))

    def _portfolios_by_name(self, portfolios):
        """
        Get list of portfolio boards matching a provided string

        Parameters
        ----------
        portfolios : list of names to match

        Returns
        -------
        list of boards

        """
        if not self.portfolio_boards:
            result = self.get("portfolio/boards.json")
            portfolio_boards = result.get("boards")
        
        self.portfolio_boards = portfolio_boards
        boards = []
        if self.portfolio_boards:
            boards = [item for item in self.portfolio_boards 
                        for portfolio_name in portfolios 
                        if re.match(portfolio_name, item.get("name"), re.I)] 

        return boards

    def _tags_by_name(self, tagnames):
        """[summary]

        Parameters
        ----------
        tagnames : list of str
            List of tags that we need to get information on

        Returns
        -------
        list of tags with name and id
        """
        if not self.tags:
            result = self.get("tags.json")
            tags = result.get("tags")

        self.tags = tags
        tagIds = []
        if self.tags:
            tagIds = [item for item in self.tags for tag_name in tagnames 
                        if re.match(tag_name, item["name"], re.I)]

        return tagIds

