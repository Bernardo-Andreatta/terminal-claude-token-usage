class ClaudeTokens < Formula
  include Language::Python::Virtualenv

  desc "Live terminal TUI tracking Claude Code token usage and cost estimates"
  homepage "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage"
  url "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "baf2ad6c133d0c6aa4ee6a88d9c91d52b531e58b3a8de68d074c355487623c0a"
  license "MIT"
  head "https://github.com/Bernardo-Andreatta/terminal-claude-token-usage.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"claude-tokens", "--help"
  rescue SystemExit
    true
  end
end
