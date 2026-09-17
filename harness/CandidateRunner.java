import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public class CandidateRunner {
    private static Class<?> typeOf(String name) throws Exception {
        switch (name) {
            case "byte": return byte.class;
            case "short": return short.class;
            case "int": return int.class;
            case "long": return long.class;
            case "float": return float.class;
            case "double": return double.class;
            case "boolean": return boolean.class;
            case "char": return char.class;
            case "java.lang.String": return String.class;
            default: return Class.forName(name);
        }
    }

    private static Object parse(String type, String b64) throws Exception {
        String value = new String(Base64.getDecoder().decode(b64), StandardCharsets.UTF_8);
        switch (type) {
            case "byte": return Byte.valueOf(value);
            case "short": return Short.valueOf(value);
            case "int": return Integer.valueOf(value);
            case "long": return Long.valueOf(value);
            case "float": return Float.valueOf(value);
            case "double": return Double.valueOf(value);
            case "boolean": return Boolean.valueOf(value);
            case "char": return value.isEmpty() ? Character.valueOf('\0') : Character.valueOf(value.charAt(0));
            case "java.lang.String": return value;
            default:
                if ("__NULL__".equals(value)) return null;
                throw new IllegalArgumentException("Unsupported argument type: " + type);
        }
    }

    private static String enc(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static void emitError(Throwable t) {
        System.out.println("STATUS=ERROR");
        System.out.println("ERROR_CLASS=" + t.getClass().getName());
        System.out.println("ERROR_MESSAGE_B64=" + enc(String.valueOf(t.getMessage())));
    }

    private static void applySetupStep(Class<?> receiverClass, Object receiver, String stepB64) throws Exception {
        String raw = new String(Base64.getDecoder().decode(stepB64), StandardCharsets.UTF_8);
        String[] fields = raw.split("\\t", -1);
        if (fields.length < 2) throw new IllegalArgumentException("Malformed setup step");

        String methodName = fields[0];
        String[] typeNames = fields[1].isEmpty() ? new String[0] : fields[1].split(",", -1);
        if (fields.length != 2 + typeNames.length) throw new IllegalArgumentException("Setup argument count mismatch");

        Class<?>[] parameterTypes = new Class<?>[typeNames.length];
        Object[] values = new Object[typeNames.length];
        for (int i = 0; i < typeNames.length; i++) {
            String spec = fields[2 + i];
            parameterTypes[i] = typeOf(typeNames[i]);
            if (spec.startsWith("N:")) {
                String helperClassName = spec.substring(2);
                Class<?> helperClass = Class.forName(helperClassName);
                values[i] = helperClass.getConstructor().newInstance();
            } else if (spec.startsWith("V:")) {
                values[i] = parse(typeNames[i], spec.substring(2));
            } else {
                throw new IllegalArgumentException("Unknown setup argument spec: " + spec);
            }
        }

        Method setup = receiverClass.getMethod(methodName, parameterTypes);
        try {
            setup.invoke(receiver, values);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause() == null ? e : e.getCause();
            throw new IllegalStateException("Setup step " + methodName + " failed: " + cause, cause);
        }
    }

    public static void main(String[] args) {
        try {
            if (args.length < 4) {
                throw new IllegalArgumentException(
                    "Usage: <class> <method> <typesCsv> <setupCount> [setupStepB64...] [valuesB64...]"
                );
            }
            String className = args[0];
            String methodName = args[1];
            String typesCsv = args[2];
            String[] typeNames = typesCsv.isEmpty() ? new String[0] : typesCsv.split(",", -1);
            int setupCount = Integer.parseInt(args[3]);
            if (setupCount < 0) throw new IllegalArgumentException("setupCount must be >= 0");
            if (args.length != 4 + setupCount + typeNames.length) {
                throw new IllegalArgumentException("Argument count mismatch");
            }

            Class<?> clazz = Class.forName(className);
            Constructor<?> ctor = clazz.getConstructor();
            Object receiver = ctor.newInstance();

            for (int i = 0; i < setupCount; i++) {
                applySetupStep(clazz, receiver, args[4 + i]);
            }

            Class<?>[] parameterTypes = new Class<?>[typeNames.length];
            Object[] values = new Object[typeNames.length];
            int valueOffset = 4 + setupCount;
            for (int i = 0; i < typeNames.length; i++) {
                parameterTypes[i] = typeOf(typeNames[i]);
                values[i] = parse(typeNames[i], args[valueOffset + i]);
            }

            Method method = clazz.getMethod(methodName, parameterTypes);
            Object result;
            try {
                result = method.invoke(receiver, values);
            } catch (InvocationTargetException e) {
                Throwable cause = e.getCause() == null ? e : e.getCause();
                System.out.println("STATUS=EXCEPTION");
                System.out.println("EXCEPTION_CLASS=" + cause.getClass().getName());
                System.out.println("EXCEPTION_MESSAGE_B64=" + enc(String.valueOf(cause.getMessage())));
                return;
            }

            System.out.println("STATUS=OK");
            System.out.println("RETURN_TYPE=" + method.getReturnType().getName());
            if (method.getReturnType() == void.class) {
                System.out.println("RETURN_KIND=VOID");
                System.out.println("RETURN_B64=");
            } else if (result == null) {
                System.out.println("RETURN_KIND=NULL");
                System.out.println("RETURN_B64=");
            } else if (result instanceof String || result instanceof Character || result instanceof Number || result instanceof Boolean) {
                System.out.println("RETURN_KIND=SCALAR");
                System.out.println("RETURN_B64=" + enc(String.valueOf(result)));
            } else {
                System.out.println("RETURN_KIND=OBJECT");
                System.out.println("RETURN_B64=" + enc(String.valueOf(result)));
            }
        } catch (Throwable t) {
            emitError(t);
            System.exit(2);
        }
    }
}
