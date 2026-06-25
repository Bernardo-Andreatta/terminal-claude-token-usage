class ClaudeTokens < Formula
  include Language::Python::Virtualenv

  desc "Live terminal TUI tracking Claude Code token usage and cost estimates"
  homepage "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage"
  url "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage/archive/refs/tags/v1.1.0.tar.gz"
  sha256 "6223c353068e22f6e24eec6aeffef8d1ead67f3a533c15fcb384907ea04761b9"
  license "MIT"
  head "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
    bin.install_symlink Dir[libexec/"bin/claude-tokens*"]
  end

  test do
    assert_predicate bin/"claude-tokens", :exist?
  end
end
