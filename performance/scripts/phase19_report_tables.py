"""Entry point for the frozen Phase19 report renderer."""
from phase19_archive_candidate import EVIDENCE, index
import sys
sys.path.insert(0,str(EVIDENCE/'protocol'))
from report_tables import read, count, resource_peaks, capacity, browser, main
if __name__=='__main__':
    main()
    index()
