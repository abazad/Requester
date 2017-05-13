import sublime_plugin

from urllib import parse

from .common import RequestCommandMixin


class RequesterCommand(RequestCommandMixin, sublime_plugin.TextCommand):
    """Execute requests concurrently from requests file and open multiple response
    views.
    """
    def get_selections(self):
        """Gets multiple selections. If nothing is highlighted, cursor's current
        line is taken as selection.
        """
        view = self.view
        selections = []
        for region in view.sel():
            if not region.empty():
                selections.append( view.substr(region) )
            else:
                selection = view.substr(view.line(region))
                if selection: # ignore empty strings, i.e. blank lines
                    selections.append(selection)
        selections = [self.prepare_selection(s) for s in selections]
        return selections

    def open_response_view(self, request, response, num_selections):
        """Create a response view and insert response content into it. Ensure that
        response tab comes after (to the right of) all other response tabs.

        Don't create new response tab if a response tab matching request is open.
        """
        window = self.view.window()
        requester_sheet = window.active_sheet()

        last_sheet = requester_sheet # find last sheet (tab) with a response view
        for sheet in window.sheets():
            view = sheet.view()
            if view and view.settings().get('requester.response_view', False):
                last_sheet = sheet
        window.focus_sheet(last_sheet)

        views = self.response_views_with_matching_selection(request)
        if not len(views): # if there are no matching response tabs, create a new one
            views = [window.new_file()]
        else: # move focus to matching view after response is returned if match occurred
            window.focus_view(views[0])

        for view in views:
            view.set_scratch(True)

            # this setting allows keymap to target response views separately
            view.settings().set('requester.response_view', True)
            view.settings().set('requester.env_string',
                                self.view.settings().get('requester.env_string', None))
            view.settings().set('requester.env_file',
                                self.view.settings().get('requester.env_file', None))
            view.settings().set('requester.selection', request)

            view.set_name('{}: {}'.format(
                response.request.method, parse.urlparse(response.url).path
            )) # short but descriptive, to facilitate navigation between response tabs using Goto Anything

            content = self.get_response_content(request, response)
            view.run_command('requester_replace_view_text',
                             {'text': content.content, 'point': content.point})
            self.set_syntax(view, response)

        if num_selections > 1:
            # keep focus on requests view if multiple requests are being executed
            window.focus_sheet(requester_sheet)


class RequesterReplayRequestCommand(RequestCommandMixin, sublime_plugin.TextCommand):
    """Replay a request from a response view.
    """
    def get_selections(self):
        """Returns only one selection, the one on the first line.
        """
        return [self.prepare_selection(
            self.view.substr( self.view.line(0) ), False
        )]

    def open_response_view(self, request, response, **kwargs):
        """Overwrites content in current view.
        """
        content = self.get_response_content(request, response)
        self.view.run_command('requester_replace_view_text',
                             {'text': content.content, 'point': content.point})
        self.set_syntax(self.view, response)
