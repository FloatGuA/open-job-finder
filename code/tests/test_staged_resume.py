"""往企业系统传简历时，暂存不能改掉文件名。

**为什么必须暂存**：没协商 MCP roots capability 时，chrome-devtools-mcp 把文件操作
限制在 OS 临时目录，`upload_file` 传项目内的路径会被它自己拒掉（见 `staged_resume`
的 docstring，2026-08-15 真机撞到过）。

**但改名是个泄漏到外面的副作用**：浏览器上传时发送的就是这个文件名，所以企业的
申请表里收到的附件叫 `ojf_resume_98084.pdf`——HR 是会看附件名的。
原来的实现把文件复制成 `ojf_resume_{pid}.pdf`，名字就这么丢了。

**修法：每次一个子目录，文件名原样保留。** 子目录同样在临时目录之下——
已对着 chrome-devtools-mcp 的源码核过它的判定：

    canonicalPath === canonicalRoot || canonicalPath.startsWith(canonicalRoot + path.sep)

（`McpContext.js`）——子目录满足第二个条件。**不是猜的。**
"""
import os
import tempfile

import pytest

from multisite.layer1_agent import staged_resume


@pytest.fixture()
def a_resume(tmp_path):
    p = tmp_path / "Agent开发_张三_2026-08-17.pdf"
    p.write_bytes(b"%PDF-1.4 hello")
    return str(p)


class TestStagedResume:
    def test_the_filename_is_preserved(self, a_resume):
        """企业收到的附件名就是这个——别让它变成 ojf_resume_12345.pdf。"""
        with staged_resume(a_resume) as staged:
            assert os.path.basename(staged) == os.path.basename(a_resume)

    def test_it_lands_under_the_os_temp_dir(self, a_resume):
        """MCP 只允许读 OS 临时目录之下的路径——离开这里 upload_file 会被它拒掉。"""
        real_tmp = os.path.realpath(tempfile.gettempdir())
        with staged_resume(a_resume) as staged:
            assert os.path.realpath(staged).startswith(real_tmp + os.sep)

    def test_the_bytes_are_the_same(self, a_resume):
        with staged_resume(a_resume) as staged:
            assert open(staged, "rb").read() == open(a_resume, "rb").read()

    def test_everything_is_cleaned_up_afterwards(self, a_resume):
        """临时目录里躺一份带真实个人信息的简历不合适——**连那个子目录一起收走**。"""
        with staged_resume(a_resume) as staged:
            path = staged
        assert not os.path.exists(path)
        assert not os.path.isdir(os.path.dirname(path))

    def test_it_is_cleaned_up_even_when_the_body_raises(self, a_resume):
        """上传中途出错是常态（表单没有文件控件、页面变了……），
        不能因此把带个人信息的简历留在临时目录里。"""
        path = None
        with pytest.raises(RuntimeError):
            with staged_resume(a_resume) as staged:
                path = staged
                raise RuntimeError("boom")
        assert path and not os.path.exists(path)
        assert not os.path.isdir(os.path.dirname(path))

    def test_two_runs_do_not_collide(self, a_resume):
        """同名文件暂存两次不能互相踩——各自一个子目录。"""
        with staged_resume(a_resume) as a:
            with staged_resume(a_resume) as b:
                assert a != b
                assert os.path.isfile(a) and os.path.isfile(b)

    def test_a_missing_source_fails_loudly(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            with staged_resume(str(tmp_path / "nope.pdf")):
                pass
