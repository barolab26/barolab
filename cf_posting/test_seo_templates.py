"""The popularity option preserves publication filters and admin authorization."""
import json
import shutil
import sqlite3
import subprocess
import unittest

from cf_posting.seo_templates import patch_public_post_sort


LIST_ROUTE = r'''
  if (method === "GET" && path === "/api/posts") {
    const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10));
    const limit = Math.min(100, Math.max(1, parseInt(url.searchParams.get("limit") || "20", 10)));
    const status = String(url.searchParams.get("status") || "published");
    const catFilter = url.searchParams.get("cat") || "";
    const searchFilter = url.searchParams.get("q") || "";
    if (status !== "published") {
      const auth = await requireAdminOrApiKey(request, db, env);
      if (!auth.ok) return auth.res;
    }
    const offset = (page - 1) * limit;
    let rows;
    if (status === "published") {
      let sql = "SELECT id, title, slug, excerpt, category, thumbnail, status, views, source, publish_at, created_at, updated_at FROM posts WHERE (redirect_to IS NULL OR redirect_to = '') AND (status='published' OR (status='scheduled' AND publish_at IS NOT NULL AND publish_at <= datetime('now')))";
      const binds = [];
      if (catFilter) {
        sql += " AND category = ?";
        binds.push(catFilter);
      }
      if (searchFilter) {
        sql += " AND (INSTR(title, ?) > 0 OR INSTR(excerpt, ?) > 0)";
        binds.push(searchFilter, searchFilter);
      }
      sql += " ORDER BY COALESCE(publish_at, created_at) DESC LIMIT ? OFFSET ?";
      binds.push(limit, offset);
      rows = await db.prepare(sql).bind(...binds).all();
    } else if (status === "scheduled") {
      rows = await db.prepare(
        "SELECT id, title, slug, excerpt, category, thumbnail, status, views, source, publish_at, created_at, updated_at FROM posts WHERE status = 'scheduled' AND (publish_at IS NULL OR publish_at > datetime('now')) ORDER BY publish_at ASC LIMIT ? OFFSET ?"
      ).bind(limit, offset).all();
    } else {
      rows = await db.prepare(
        "SELECT id, title, slug, excerpt, category, thumbnail, status, views, source, publish_at, created_at, updated_at FROM posts WHERE status = ? ORDER BY COALESCE(publish_at, created_at) DESC LIMIT ? OFFSET ?"
      ).bind(status, limit, offset).all();
    }
    return json({ success: true, posts: rows.results || [], page, limit });
  }
  if (method === "POST" && path === "/api/posts") {
    return "unchanged";
  }
'''


class PublicPostSortTests(unittest.TestCase):
    def test_narrow_idempotent_and_rejects_unknown_route(self):
        original = "prefix\n" + LIST_ROUTE + "\nsuffix"
        patched = patch_public_post_sort(original)
        self.assertEqual(patch_public_post_sort(patched), patched)
        self.assertEqual(patched[:patched.index('  if (method === "GET"')], "prefix\n\n")
        self.assertTrue(patched.endswith('    return "unchanged";\n  }\n\nsuffix'))
        with self.assertRaises(ValueError):
            patch_public_post_sort(original.replace("COALESCE(publish_at, created_at) DESC LIMIT", "id DESC LIMIT"))
        with self.assertRaises(ValueError):
            patch_public_post_sort(patched.replace("page, limit, sort", "page, limit"))

    @unittest.skipUnless(shutil.which("node"), "Node required for real Worker branch execution")
    def test_runtime_sort_auth_filters_and_pagination(self):
        route = patch_public_post_sort(LIST_ROUTE)
        script = """
const logs = [];
async function run(query, allowed=false) {
  let captured=null, authCalls=0;
  const request={}, env={}, method="GET", path="/api/posts";
  const url=new URL("https://example.com/api/posts?"+query);
  const db={prepare(sql){return {bind(...args){captured={sql,args};return {async all(){return {results:[]};}};}};}};
  const requireAdminOrApiKey=async()=>{authCalls++;return {ok:allowed,res:{status:401}};};
  const json=x=>x;
  async function handler() { ROUTE }
  const response=await handler();
  return {response,captured,authCalls};
}
(async()=>{
  for(const q of ["sort=views&limit=2", "limit=2", "sort=views&status=draft",
      "sort=views&limit=2&page=2&cat=news&q=title", "sort=views%3BDELETE"]){
    logs.push(await run(q));
  }
  console.log(JSON.stringify(logs));
})().catch(()=>process.exit(1));
""".replace("ROUTE", route)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        popular, recent, denied, filtered, unknown = json.loads(result.stdout)
        self.assertEqual(popular["response"]["sort"], "views")
        self.assertEqual(recent["response"]["sort"], "recent")
        self.assertEqual(unknown["response"]["sort"], "recent")
        self.assertEqual(denied, {"response": {"status": 401}, "captured": None, "authCalls": 1})
        self.assertEqual(filtered["captured"]["args"], ["news", "title", "title", 2, 2])
        self.assertEqual(popular["authCalls"], 0)
        with sqlite3.connect(":memory:") as db:
            db.execute("""CREATE TABLE posts(id INTEGER, title TEXT, slug TEXT, excerpt TEXT,
                category TEXT, thumbnail TEXT, status TEXT, views INTEGER, source TEXT,
                publish_at TEXT, created_at TEXT, updated_at TEXT, redirect_to TEXT)""")
            for row in [
                (1, "published", 2, None, "2025-01-01", None),
                (2, "published", 9, None, "2024-01-01", None),
                (3, "published", 9, None, "2023-01-01", None),
                (4, "draft", 100, None, "2026-01-01", None),
                (5, "scheduled", 100, "2999-01-01", "2026-01-01", None),
                (6, "published", 100, None, "2026-01-01", "/redirect"),
                (7, "scheduled", 4, "2000-01-01", "2000-01-01", None),
            ]:
                db.execute("INSERT INTO posts(id,status,views,publish_at,created_at,redirect_to) VALUES(?,?,?,?,?,?)", row)
            self.assertEqual([r[0] for r in db.execute(popular["captured"]["sql"],
                                                     popular["captured"]["args"])], [3, 2])
            self.assertEqual([r[0] for r in db.execute(recent["captured"]["sql"],
                                                     recent["captured"]["args"])], [1, 2])
            self.assertEqual([r[0] for r in db.execute(popular["captured"]["sql"], [100, 0])],
                             [3, 2, 7, 1])


if __name__ == "__main__":
    unittest.main()
