from PySide.QtGui import *
from PySide.QtCore import *
import sys
import pyqtgraph as pg
import numpy as np
from utils import replace_dataset
import utils as utils
import h5py
import arf
import pyqtgraph.functions as fn

class labelRegion(pg.LinearRegionItem):
    '''Labeled region on label plot'''
    def __init__(self, name, start, stop, parent, line_color=None,*args, **kwargs):
        super(labelRegion, self).__init__([start, stop], *args, **kwargs)
        parent.addItem(self)  
        self.text = pg.TextItem(name)
        self.text.setScale(2)
        parent.addItem(self.text)
        self.position_text_y()
        self.position_text_x()
        self.setMovable(False)
        if line_color is not None:
            for line,color in zip(self.lines,line_color):
                line.setPen(fn.mkPen(color))
        
    def position_text_y(self):
        yrange=self.getViewBox().viewRange()[1]
        self.text.setY(np.mean(yrange))

    def position_text_x(self):
        if self.getViewBox() is None:
            print(self.getRegion())
        else:
            xmin, xmax = self.getViewBox().viewRange()[0]
            if xmin <= self.getRegion()[0] <= xmax:
                self.text.setX(self.getRegion()[0])
            elif self.getRegion()[0] < xmin < self.getRegion()[1]:
                self.text.setX(xmin)

            
class labelPlot(pg.PlotItem):
    '''Interactive plot for making and displaying labels

    Parameters:
    lbl - complex label dataset
    '''
    sigLabelSelected = Signal()
    sigNoLabelSelected = Signal()
    
    def __init__(self, file, path, *args, **kwargs):
        super(labelPlot, self).__init__(*args, **kwargs)
        lbl = file[path]
        if not utils.is_complex_event(lbl):           
            raise TypeError("Argument must be complex event dataset")
        elif lbl.maxshape != (None,):
            raise TypeError("Argument must have maxshape (None,)")
        else:
             self.lbl = lbl
        #saving the file and the path allows access to non-anonymous reference to
        #the dataset, which is necessary for deleting labels
        self.file = file
        self.path = path          
        self.double_clicked = np.zeros(len(self.lbl),dtype=bool)
        self.installEventFilter(self)
        self.getViewBox().enableAutoRange(enable=False)
        self.key = None
        self.dclickedRegion = None
        self.activeLabel = None
        if self.lbl.attrs['units'] == 'ms':
            self.scaling_factor = 1000
        elif self.lbl.attrs['units'] == 'samples':
            self.scaling_factor = self.lbl.attrs['sampling_rate']
        else:
            self.scaling_factor = 1
        self.setMouseEnabled(y=False)
        self.max_plotted = 100
        self.getViewBox().sigXRangeChanged.connect(self.plot_all_events)
        self.plot_all_events()
        
    def plot_all_events(self):
        self.clear()
        if len(self.lbl) == 0: return 
        t_min,t_max = self.getAxis('bottom').range
        names = self.lbl['name']
        starts = self.lbl['start']/self.scaling_factor
        stops = self.lbl['stop']/self.scaling_factor
        first_idx = next((i for i in xrange(len(self.lbl)) if
                          stops[i]>t_min),0)
        last_idx = next((i for i in xrange(len(self.lbl)-1,0,-1)
                    if starts[i]<t_max),first_idx)
        n = last_idx - first_idx
        #labels that will be plotted
        if n > self.max_plotted:
            plotted_idx = (first_idx + int(np.ceil(i*n/self.max_plotted))
                           for i in xrange(self.max_plotted) )
        else:
            plotted_idx = xrange(first_idx,last_idx+1)

        #Keeps track of previous label so that if the stop of a red label equals
        #the start of the next, the red line from
        #the previous label won't be drawn over
        prev_was_clicked = False
        prev_stop = None
        for i in plotted_idx:
            if self.double_clicked[i]:
                line_color = ['r','r']
                prev_was_clicked = True
            elif prev_was_clicked and prev_stop == self.lbl[i]['start']:
                line_color = ['y','r']
                prev_was_clicked = False
            else:
                line_color = None
                prev_was_clicked = False
                
            self.plot_complex_event(self.lbl[i],line_color=line_color)
            prev_stop = self.lbl[i]['stop']

        self.setActive(True)
            
    def plot_complex_event(self, complex_event, line_color=None, with_text=True):
        '''Plots a single event'''
        name = complex_event['name']
        start = complex_event['start'] / self.scaling_factor
        stop = complex_event['stop'] / self.scaling_factor
        region = labelRegion(name, start, stop, parent=self, line_color=line_color)
        
        return region
        
    def sort_lbl(self):
        '''Sorts lbl dataset by start time'''
        data = self.lbl[:]
        sort_idx = data.argsort(order='start')
        data.sort(order='start')
        self.lbl[:] = data
        self.double_clicked = self.double_clicked[sort_idx]

    def delete_selected_labels(self):
        win = self.parentWidget().getViewWidget()
        reply = QMessageBox.question(win,"","Delete selected labels?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        try:
            if reply == QMessageBox.Yes:
                new_data = self.lbl[np.negative(self.double_clicked)]
                lbl = self.file[self.path] #non-anonymous lbl entry
                replace_dataset(lbl, lbl.parent, data=new_data, maxshape=(None,))
                self.lbl = self.file[self.path]
                self.double_clicked = np.zeros(len(self.lbl),dtype=bool)
                self.plot_all_events()
                self.sigNoLabelSelected.emit()
        except:
            QMessageBox.critical(win,"", "Could not delete label. Make sure you have write permission for this file.", QMessageBox.Ok)
            
                
    def keyPressEvent(self, event):
        print(event.key())
        print(self.double_clicked)
        if event.text().isalpha():
            event.accept()
            self.key = event.text().lower()
        elif (event.key() in (Qt.Key_Delete, Qt.Key_Backspace) #delete label
              and np.any(self.double_clicked)):
            event.accept()
            self.delete_selected_labels()
        else:
            event.ignore()

    def keyReleaseEvent(self, event):
        if event.text().lower() == self.key:
            event.accept()
            self.key = None
        else:
            event.ignore()
            
    def mouseClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos=self.getViewBox().mapSceneToView(event.scenePos())
            t = pos.x() * self.scaling_factor
            if self.key and not self.activeLabel:
                arf.append_data(self.lbl, (self.key, t, t))
                self.activeLabel = self.plot_complex_event(self.lbl[-1])
                self.double_clicked = np.zeros(len(self.lbl),dtype=bool)
                if event.modifiers() != Qt.ShiftModifier:
                    self.sort_lbl()
                    self.activeLabel = None
            elif self.activeLabel:
                if t >= self.lbl[-1]['start']:
                    self.lbl[-1] = (self.lbl[-1]['name'], self.lbl[-1]['start'], t)
                else:
                    self.lbl[-1] =  (self.lbl[-1]['name'], t, self.lbl[-1]['stop'])

                new_region = (np.array([self.lbl[-1]['start'], self.lbl[-1]['stop']])/ 
                              self.scaling_factor)

                self.activeLabel.setRegion(new_region)
                self.activeLabel = None
                self.sort_lbl()
    
            
    def mouseDoubleClickEvent(self, event):
        if self.activeLabel: return
        previously_clicked = list(self.double_clicked)
        pos = event.scenePos()
        vb = self.getViewBox()
        pixel_margin = 2
        for i,(start,stop) in enumerate(zip(self.lbl['start'],self.lbl['stop'])):
            scene_start =  vb.mapViewToScene(QPointF(start/self.scaling_factor,0)).x()
            scene_stop = vb.mapViewToScene(QPointF(stop/self.scaling_factor,0)).x()
            if scene_start - pixel_margin < pos.x() < scene_stop + pixel_margin:
                self.double_clicked[i] = not self.double_clicked[i]
                
        self.plot_all_events()
        if any(self.double_clicked) and not any(previously_clicked):
            event.accept()
            if not any(previously_clicked):
                self.sigLabelSelected.emit()
        elif not any(self.double_clicked):
            event.ignore()
            if any(previously_clicked):
                self.sigNoLabelSelected.emit()

