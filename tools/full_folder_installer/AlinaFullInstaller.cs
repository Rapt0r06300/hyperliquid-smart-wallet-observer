using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

internal static class AlinaFullInstaller
{
    private const string ManifestName = "ALINA_FULL_FOLDER_RELEASE.json";

    private static int Main(string[] args)
    {
        try
        {
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
            Options options = Options.Parse(args);
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("Alina SmartFlow - installation complète");
            Console.WriteLine("Version Git : " + ReleaseInfo.GitHead);
            Console.WriteLine("Destination : " + options.Destination);
            if (!options.Yes)
            {
                Console.Write("Télécharger et installer la copie complète ? [o/N] ");
                string answer = Console.ReadLine() ?? "";
                if (!answer.Equals("o", StringComparison.OrdinalIgnoreCase) && !answer.Equals("oui", StringComparison.OrdinalIgnoreCase))
                    return 1;
            }

            EnsureDestinationAvailable(options.Destination);
            Directory.CreateDirectory(options.Cache);
            string manifestPath = Path.Combine(options.Cache, ManifestName);
            DownloadResumable(options.ManifestUrl, manifestPath, null);
            VerifyFile(manifestPath, ReleaseInfo.ManifestSha256, null);
            IDictionary<string, object> manifest = ReadJson(manifestPath);
            VerifyManifestIdentity(manifest);

            IDictionary<string, object> inventoryInfo = Dict(manifest["inventory"]);
            string inventoryName = Text(inventoryInfo["name"]);
            string inventoryPath = Path.Combine(options.Cache, inventoryName);
            DownloadResumable(AssetUrl(options.BaseUrl, inventoryName), inventoryPath, Number(inventoryInfo["size"]));
            VerifyFile(inventoryPath, Text(inventoryInfo["sha256"]), Number(inventoryInfo["size"]));

            object[] assets = List(manifest["archive_assets"]);
            long total = 0;
            foreach (object value in assets) total += Number(Dict(value)["size"]);
            long completed = 0;
            foreach (object value in assets)
            {
                IDictionary<string, object> asset = Dict(value);
                string name = Text(asset["name"]);
                long size = Number(asset["size"]);
                Console.WriteLine("Volume " + name + " (" + FormatBytes(size) + ")");
                string local = Path.Combine(options.Cache, name);
                DownloadResumable(AssetUrl(options.BaseUrl, name), local, size);
                VerifyFile(local, Text(asset["sha256"]), size);
                completed += size;
                Console.WriteLine("Volumes validés : " + FormatBytes(completed) + " / " + FormatBytes(total));
            }

            string parent = Path.GetDirectoryName(options.Destination.TrimEnd(Path.DirectorySeparatorChar));
            if (String.IsNullOrEmpty(parent)) throw new InvalidOperationException("Destination invalide");
            Directory.CreateDirectory(parent);
            string staging = Path.Combine(parent, ".alina-installation-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(staging);
            try
            {
                string sevenZip = ExtractResource("Alina.Embedded.7z.exe", Path.Combine(options.Cache, "7z.exe"));
                ExtractResource("Alina.Embedded.7z.dll", Path.Combine(options.Cache, "7z.dll"));
                string firstPart = Path.Combine(options.Cache, Text(manifest["archive_first_part"]));
                RunSevenZip(sevenZip, firstPart, staging);
                VerifyInstalledTree(staging, inventoryPath);
                Directory.Move(staging, options.Destination);
            }
            catch
            {
                Console.Error.WriteLine("Installation incomplète conservée pour diagnostic : " + staging);
                throw;
            }

            if (!options.KeepCache)
                foreach (object value in assets) File.Delete(Path.Combine(options.Cache, Text(Dict(value)["name"])));
            File.WriteAllText(Path.Combine(options.Cache, "INSTALLATION_OK.txt"), DateTime.UtcNow.ToString("O") + "\r\n" + options.Destination + "\r\n", Encoding.UTF8);
            Console.WriteLine("Installation vérifiée : " + options.Destination);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("ERREUR : " + error.Message);
            return 2;
        }
    }

    private static string AssetUrl(string baseUrl, string name)
    {
        return baseUrl.TrimEnd('/') + "/" + Uri.EscapeDataString(name);
    }

    private static void DownloadResumable(string url, string path, long? expectedSize)
    {
        if (File.Exists(path) && expectedSize.HasValue && new FileInfo(path).Length == expectedSize.Value) return;
        long existing = File.Exists(path) ? new FileInfo(path).Length : 0;
        if (expectedSize.HasValue && existing > expectedSize.Value) { File.Delete(path); existing = 0; }
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
        request.UserAgent = "Alina-SmartFlow-Full-Installer/1.0";
        request.AllowAutoRedirect = true;
        request.Timeout = 60000;
        request.ReadWriteTimeout = 60000;
        if (existing > 0) request.AddRange(existing);
        using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
        {
            bool append = existing > 0 && response.StatusCode == HttpStatusCode.PartialContent;
            if (!append) existing = 0;
            using (Stream input = response.GetResponseStream())
            using (FileStream output = new FileStream(path, append ? FileMode.Append : FileMode.Create, FileAccess.Write, FileShare.None, 8 * 1024 * 1024))
            {
                byte[] buffer = new byte[8 * 1024 * 1024];
                long lastReport = existing;
                int read;
                while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                {
                    output.Write(buffer, 0, read);
                    existing += read;
                    if (existing - lastReport >= 512L * 1024 * 1024)
                    {
                        Console.WriteLine("  téléchargé : " + FormatBytes(existing));
                        lastReport = existing;
                    }
                }
            }
        }
    }

    private static void VerifyFile(string path, string expectedHash, long? expectedSize)
    {
        FileInfo info = new FileInfo(path);
        if (expectedSize.HasValue && info.Length != expectedSize.Value) throw new InvalidDataException("taille incorrecte : " + info.Name);
        string actual = Sha256(path);
        if (!actual.Equals(expectedHash, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("SHA-256 incorrect : " + info.Name);
    }

    private static string Sha256(string path)
    {
        using (SHA256 sha = SHA256.Create())
        using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 8 * 1024 * 1024, FileOptions.SequentialScan))
        {
            byte[] hash = sha.ComputeHash(stream);
            StringBuilder text = new StringBuilder(hash.Length * 2);
            foreach (byte value in hash) text.Append(value.ToString("x2", CultureInfo.InvariantCulture));
            return text.ToString();
        }
    }

    private static void VerifyManifestIdentity(IDictionary<string, object> manifest)
    {
        if (Number(manifest["schema_version"]) != 1) throw new InvalidDataException("version de manifeste inconnue");
        if (!Text(manifest["repository"]).Equals(ReleaseInfo.Repository, StringComparison.Ordinal)) throw new InvalidDataException("dépôt inattendu");
        if (!Text(manifest["tag"]).Equals(ReleaseInfo.Tag, StringComparison.Ordinal)) throw new InvalidDataException("tag inattendu");
        if (!Text(manifest["git_head"]).Equals(ReleaseInfo.GitHead, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("SHA Git inattendu");
    }

    private static void RunSevenZip(string executable, string firstPart, string staging)
    {
        ProcessStartInfo info = new ProcessStartInfo(executable, "x \"" + firstPart + "\" -o\"" + staging + "\" -y -bsp1");
        info.UseShellExecute = false;
        info.WorkingDirectory = staging;
        Process process = Process.Start(info);
        if (process == null) throw new InvalidOperationException("7-Zip ne démarre pas");
        process.PriorityClass = ProcessPriorityClass.BelowNormal;
        process.WaitForExit();
        if (process.ExitCode != 0) throw new InvalidDataException("7-Zip a échoué, code " + process.ExitCode);
    }

    private static void VerifyInstalledTree(string staging, string inventoryPath)
    {
        IDictionary<string, object> inventory = ReadJson(inventoryPath);
        object[] entries = List(inventory["entries"]);
        int done = 0;
        foreach (object raw in entries)
        {
            IDictionary<string, object> entry = Dict(raw);
            string relative = Text(entry["path"]);
            string destination = SafeChild(staging, relative);
            string kind = Text(entry["kind"]);
            if (kind == "file") VerifyFile(destination, Text(entry["sha256"]), Number(entry["size"]));
            else if (kind == "directory") Directory.CreateDirectory(destination);
            done++;
            if (done % 5000 == 0) Console.WriteLine("Fichiers vérifiés : " + done + " / " + entries.Length);
        }
        foreach (object raw in entries)
        {
            IDictionary<string, object> entry = Dict(raw);
            if (Text(entry["kind"]) != "junction") continue;
            string link = SafeChild(staging, Text(entry["path"]));
            string target = SafeChild(staging, Text(entry["target"]));
            Directory.CreateDirectory(Path.GetDirectoryName(link));
            ProcessStartInfo info = new ProcessStartInfo("cmd.exe", "/d /c mklink /J \"" + link + "\" \"" + target + "\"");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process process = Process.Start(info);
            if (process == null) throw new InvalidOperationException("mklink ne démarre pas");
            process.WaitForExit();
            if (process.ExitCode != 0) throw new InvalidDataException("jonction impossible : " + entry["path"]);
        }
    }

    private static string SafeChild(string root, string relative)
    {
        string rootFull = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string child = Path.GetFullPath(Path.Combine(rootFull, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!child.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("chemin hors destination : " + relative);
        return child;
    }

    private static string ExtractResource(string name, string destination)
    {
        Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
        if (input == null) throw new InvalidOperationException("ressource absente : " + name);
        using (input)
        using (FileStream output = File.Create(destination)) input.CopyTo(output);
        return destination;
    }

    private static IDictionary<string, object> ReadJson(string path)
    {
        IDictionary<string, object> result = new JavaScriptSerializer { MaxJsonLength = int.MaxValue, RecursionLimit = 100 }.DeserializeObject(File.ReadAllText(path, Encoding.UTF8)) as IDictionary<string, object>;
        if (result == null) throw new InvalidDataException("JSON invalide : " + path);
        return result;
    }

    private static IDictionary<string, object> Dict(object value) { return (IDictionary<string, object>)value; }
    private static object[] List(object value) { return (object[])value; }
    private static string Text(object value) { return Convert.ToString(value, CultureInfo.InvariantCulture) ?? ""; }
    private static long Number(object value) { return Convert.ToInt64(value, CultureInfo.InvariantCulture); }
    private static string FormatBytes(long size) { return (size / 1073741824.0).ToString("0.00", CultureInfo.InvariantCulture) + " Gio"; }

    private static void EnsureDestinationAvailable(string destination)
    {
        if (Directory.Exists(destination) && Directory.GetFileSystemEntries(destination).Length != 0) throw new IOException("la destination existe et n'est pas vide : " + destination);
        if (File.Exists(destination)) throw new IOException("un fichier occupe la destination : " + destination);
    }

    private sealed class Options
    {
        public string Destination = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Projet AlinaSmartFlow");
        public string Cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AlinaSmartFlow", "downloads", ReleaseInfo.Tag);
        public bool Yes;
        public bool KeepCache;
        public string BaseUrl = "https://github.com/" + ReleaseInfo.Repository + "/releases/download/" + Uri.EscapeDataString(ReleaseInfo.Tag);
        public string ManifestUrl { get { return BaseUrl.TrimEnd('/') + "/" + ManifestName; } }

        public static Options Parse(string[] args)
        {
            Options result = new Options();
            for (int index = 0; index < args.Length; index++)
            {
                if (args[index] == "--yes") result.Yes = true;
                else if (args[index] == "--keep-cache") result.KeepCache = true;
                else if (args[index] == "--destination" && ++index < args.Length) result.Destination = Path.GetFullPath(args[index]);
                else if (args[index] == "--cache" && ++index < args.Length) result.Cache = Path.GetFullPath(args[index]);
                else if (args[index] == "--base-url" && ++index < args.Length) result.BaseUrl = args[index];
                else throw new ArgumentException("argument inconnu ou incomplet : " + args[index]);
            }
            return result;
        }
    }
}
