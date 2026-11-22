"""Dock actual Win32 application windows with verified geometry and restoration."""
import os,time,threading

class NativeWindowHost:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('Native window docking requires Windows')
        import win32gui,win32con,win32process
        self.gui=win32gui;self.constants=win32con;self.process=win32process
        self.windows={}

    def top_windows(self):
        rows=[]
        def visit(hwnd,_):
            if self.gui.GetWindow(hwnd,self.constants.GW_OWNER):return
            if self.gui.GetClassName(hwnd) not in ('Chrome_WidgetWin_1','Chrome_WidgetWin_0'):return
            title=self.gui.GetWindowText(hwnd)
            if not title:return
            _,pid=self.process.GetWindowThreadProcessId(hwnd)
            left,top,right,bottom=self.gui.GetWindowRect(hwnd)
            if right-left>100 and bottom-top>100:rows.append({'hwnd':hwnd,'pid':pid,'title':title})
        self.gui.EnumWindows(visit,None)
        return rows

    def dock(self,kind,hwnd,parent,owned):
        if not self.gui.IsWindow(hwnd) or not self.gui.IsWindow(parent):raise RuntimeError('Native window is no longer available')
        style=self.gui.GetWindowLong(hwnd,self.constants.GWL_STYLE)
        original_parent=self.gui.GetParent(hwnd);rect=self.gui.GetWindowRect(hwnd)
        try:
            self.gui.ShowWindow(hwnd,self.constants.SW_HIDE)
            child_style=(style&~(self.constants.WS_POPUP|self.constants.WS_CAPTION|self.constants.WS_THICKFRAME))|self.constants.WS_CHILD
            self.gui.SetWindowLong(hwnd,self.constants.GWL_STYLE,child_style)
            self.gui.SetParent(hwnd,parent)
            if self.gui.GetParent(hwnd)!=parent:raise RuntimeError('The original window could not be embedded')
            self.windows[kind]={'hwnd':hwnd,'parent':parent,'style':style,'original_parent':original_parent,'rect':rect,'owned':owned,'last_used':time.monotonic(),'closing':False}
            self.resize(kind)
        except Exception:
            self.gui.SetParent(hwnd,original_parent);self.gui.SetWindowLong(hwnd,self.constants.GWL_STYLE,style)
            self.gui.ShowWindow(hwnd,self.constants.SW_SHOW)
            raise

    def resize(self,kind):
        row=self.windows.get(kind)
        if not row or not self.gui.IsWindow(row['hwnd']):return
        _,_,width,height=self.gui.GetClientRect(row['parent'])
        self.gui.SetWindowPos(row['hwnd'],0,0,0,max(1,width),max(1,height),self.constants.SWP_NOZORDER|self.constants.SWP_NOACTIVATE|self.constants.SWP_FRAMECHANGED)

    def show(self,kind):
        for name,row in self.windows.items():
            if self.gui.IsWindow(row['hwnd']):self.gui.ShowWindow(row['hwnd'],self.constants.SW_SHOW if name==kind else self.constants.SW_HIDE)
        if kind in self.windows:self.windows[kind]['last_used']=time.monotonic();self.resize(kind)

    def close(self,kind):
        row=self.windows.get(kind)
        if not row:return
        if self.gui.IsWindow(row['hwnd']):
            self.gui.PostMessage(row['hwnd'],self.constants.WM_CLOSE,0,0)
            row['closing']=True;row['close_requested_at']=time.monotonic()
            if row['owned']:
                _,pid=self.process.GetWindowThreadProcessId(row['hwnd'])
                def graceful():
                    from serve.native_graceful_shutdown import shutdown
                    try:row['shutdown_result']=shutdown(pid)
                    except (OSError,RuntimeError) as error:row['shutdown_result']={'stopped':False,'error':str(error)}
                threading.Thread(target=graceful,daemon=True).start()
        else:self.windows.pop(kind,None)

    def restore(self,kind):
        row=self.windows.pop(kind,None)
        if not row or not self.gui.IsWindow(row['hwnd']):return
        self.gui.SetParent(row['hwnd'],row['original_parent']);self.gui.SetWindowLong(row['hwnd'],self.constants.GWL_STYLE,row['style'])
        left,top,right,bottom=row['rect'];self.gui.SetWindowPos(row['hwnd'],0,left,top,right-left,bottom-top,self.constants.SWP_NOZORDER|self.constants.SWP_FRAMECHANGED)
        self.gui.ShowWindow(row['hwnd'],self.constants.SW_SHOW)

    def snapshot(self):
        rows={}
        for kind,row in list(self.windows.items()):
            if not self.gui.IsWindow(row['hwnd']):self.windows.pop(kind,None);continue
            _,pid=self.process.GetWindowThreadProcessId(row['hwnd']);rect=self.gui.GetWindowRect(row['hwnd'])
            rows[kind]={'hwnd':row['hwnd'],'parent':self.gui.GetParent(row['hwnd']),'expected_parent':row['parent'],
                        'embedded':self.gui.GetParent(row['hwnd'])==row['parent'],'pid':pid,'title':self.gui.GetWindowText(row['hwnd']),
                        'visible':bool(self.gui.IsWindowVisible(row['hwnd'])),'width':rect[2]-rect[0],'height':rect[3]-rect[1],
                        'owned':row['owned'],'closing':row['closing']}
            if row.get('shutdown_result'):rows[kind]['shutdown_result']=row['shutdown_result']
        return rows
