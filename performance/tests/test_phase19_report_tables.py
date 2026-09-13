from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase19_report_tables import count, resource_peaks, browser


class ReportTablesTests(unittest.TestCase):
    def test_status_and_phase_counts_never_include_rejections_as_success(self):
        aggregate={'counts':{'http_reqs|{"phase":"observe","status":"200"}':20,
            'http_reqs|{"phase":"observe","status":"503"}':10,
            'http_reqs|{"phase":"warmup","status":"200"}':50}}
        self.assertEqual(count(aggregate,'http_reqs',phase='observe',status='200'),20)
        self.assertEqual(count(aggregate,'http_reqs',phase='observe',status='503'),10)

    def test_pg_cpu_is_relative_to_its_actual_one_cpu_quota(self):
        point={'cpuFraction':.4,'linuxAvailable':1000,'oom':False,'restarted':False}
        rows=[{'postgres':point,'generator':point}]
        peaks=resource_peaks(rows)
        self.assertEqual(peaks['postgres']['cpuQuotaFractionPeak'],.8)
        self.assertEqual(peaks['generator']['cpuQuotaFractionPeak'],.4)

    def test_browser_keeps_setup_user_actions_and_other_endpoints_distinct(self):
        point={'phases':[{'activationEpochMs':10}],'requests':[
            {'startEpochMs':1,'method':'GET','business':'notifications','endpoint':'/notifications','decodedBodyBytes':100},
            {'startEpochMs':11,'method':'GET','business':'notifications','endpoint':'/notifications','decodedBodyBytes':100},
            {'startEpochMs':12,'method':'POST','business':'payment','endpoint':'/pay','decodedBodyBytes':200},
            {'startEpochMs':13,'method':'GET','business':'other','endpoint':'/sessions','decodedBodyBytes':300}],
            'checks':{},'errors':[]}
        summary=browser(point)
        self.assertEqual(summary['allHttpIncludingSetup'],4)
        self.assertEqual(summary['timedHttp'],3)
        self.assertEqual(summary['timedGovernedGet'],1)
        self.assertEqual(summary['timedDecodedBodyBytes'],600)


if __name__=='__main__':unittest.main()
