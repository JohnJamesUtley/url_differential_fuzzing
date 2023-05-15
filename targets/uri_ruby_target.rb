#!/usr/bin/env ruby

require 'uri'
require 'base64'
require 'afl'

def main
    url_string = STDIN.read
    parsed_url = URI(url_string)

    result = Hash.new
    result["scheme"] = parsed_url.scheme
    result["userinfo"] = "#{parsed_url.user}#{parsed_url.password != nil ? (":#{parsed_url.password}") : ""}"
    result["host"] = parsed_url.host
    result["port"] = parsed_url.port
    result["path"] = parsed_url.path
    result["query"] = parsed_url.query
    result["fragment"] = parsed_url.fragment

    pairs = Array.new
    # Python-Like Generators would require an extra import
    result.keys.each do |key|
        pairs.append("\"#{key}\":\"#{result[key] != nil ? Base64.encode64(result[key].to_s.dup.force_encoding('ascii')).strip : ""}\"")
    end
    print "{"
    print pairs.join(",")
    print "}"
end

if __FILE__ == $0

    unless ENV['NO_AFL']
        AFL.init
    end

    AFL.with_exceptions_as_crashes do
        main()
    end
end