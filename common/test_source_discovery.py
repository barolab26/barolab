import unittest
from unittest.mock import Mock,patch
from common.source_discovery import search_urls


class SourceDiscoveryTests(unittest.TestCase):
    def test_naver_results_are_urls_only_and_local_credential_urls_are_rejected(self):
        response=Mock(status_code=200);response.json.return_value={'items':[
            {'title':'<b>공식</b> 안내','link':'https://www.gov.kr/help','description':'NOT BODY EVIDENCE'},
            {'title':'private','link':'https://localhost/secret'},
            {'title':'credentials','link':'https://user:pass@example.com/'},
            {'title':'다른 자료','link':'https://www.nps.or.kr/help'}]}
        with patch('dotenv.load_dotenv'),patch.dict('os.environ',{'NAVER_CLIENT_ID':'fixture','NAVER_CLIENT_SECRET':'private'}),patch('common.source_discovery.requests.get',return_value=response) as get:
            rows=search_urls('제도 기준')
        self.assertEqual(len(rows),2);self.assertEqual(get.call_count,3)
        self.assertEqual(rows[0]['title'],'공식 안내');self.assertNotIn('NOT BODY',str(rows));self.assertNotIn('private',str(rows))

if __name__=='__main__':unittest.main()
